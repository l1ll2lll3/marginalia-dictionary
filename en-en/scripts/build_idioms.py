#!/usr/bin/env python3
"""dict.db에 숙어 표를 얹는다. 숙어 목록은 kaikki-en.jsonl에서 직접 뽑는다.

    python en-en/scripts/build_idioms.py             # build_dict_db.py 다음에 실행 (~1분)
    python en-en/scripts/build_idioms.py --compare   # 옛 english_idioms.json과의 차이를 예시와 함께
    python en-en/scripts/build_idioms.py --check "take into account" "make up one's mind"

설계는 docs/idiom_detection.md. 예전에는 reading에서 만든 english_idioms.json을 넣었는데,
그 목록의 선정 기준이 남아 있지 않고 뜻도 첫 뜻 하나뿐이었다.

숙어로 넣는 항목 (여러 단어 표제어 중 하나라도 맞으면):
  ① 품사가 명사·고유명사가 아니다 (verb, adj, adv, prep, phrase, proverb …) — qualifies() 참고
  ② 뜻에 idiomatic 태그  ③ 구동사 범주(English phrasal verbs formed with "X")
  ④ 명사: figuratively 태그, 또는 문자 그대로의 뜻이 따로 있다
활용형(took into account)·이형(pull up one's socks) 항목은 따로 넣지 않고 원형에 붙인다.

만드는 표:
  idioms          숙어 하나 = kaikki 원형 항목 하나. meaning은 첫 숙어 뜻 (문자 그대로의 뜻 제외)
  idiom_senses    뜻 전부 + 태그. 문자 그대로의 뜻("Used other than figuratively")은 literal=1
  idiom_examples  뜻별 예문. 평가(eval_idioms.py)와 화면 표시에 쓴다
  idiom_forms     활용형·이형 → 원형 (이름 검색용)
  idiom_patterns  탐지용 패턴. 원형과 이형마다 하나씩
  idiom_words     숙어별 고정 단어 색인. 사전 검색 후보에 쓴다 (server.py의 idiom_candidates)
"""

import argparse
import json
import re
import sqlite3
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import spacy

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_dict_db import normalize  # noqa: E402

if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

DATA = Path(__file__).resolve().parent.parent / "data"
KAIKKI = DATA / "raw" / "kaikki-en.jsonl"
OLD_IDIOMS = DATA / "raw" / "english_idioms.json"
DB_PATH = DATA / "build" / "dict.db"

EXCLUDED_POS = {"noun", "name", "punct", "circumfix", "contraction"}
PHRASAL_CAT = re.compile(r'^English phrasal verbs formed with "([^"]+)"$')
LITERAL_GLOSS = "other than figuratively or idiomatically"

# 예문 자리에 들어온 유의어 목록 줄 ("Near-synonyms: break-in, housebreaking")
NYM_LINE = re.compile(r"^(near-)?(synonyms?|antonyms?|hypernyms?|hyponyms?|coordinate terms?|see also)\s*:", re.I)

# 자리표시어 (docs/idiom_detection.md §3). 소유격은 토큰 두 개(one + 's)로 나뉜다
POSS_WORDS = {"one", "someone", "somebody"}
NP_WORDS = {"someone", "somebody", "something"}
REFL_WORDS = {"oneself"}

# 전치사로만 쓰이는 말. 동사 숙어가 이걸로 끝나면 목적어는 맨 뒤에 온다
# (look up to him, get rid of it) — 동사 바로 뒤에 목적어 자리를 두지 않는다
PREP_ONLY = {
    "of", "with", "to", "for", "at", "from", "into", "onto", "upon", "like", "than", "as",
    "against", "toward", "towards", "without", "within", "among", "amongst", "between",
    "until", "till", "via", "per", "despite", "except", "beside", "besides",
}

# 동사 바로 다음 단어의 Wiktionary 품사로 목적어 자리를 둘지 정한다 (particle_like_words)
OBJ_BEFORE_POS = {"adv", "prep", "adj", "particle", "postp"}
NOMINAL_POS = {"article", "det", "pron"}


def apostrophe(text: str) -> str:
    return text.replace("’", "'")


def categories(entry) -> set[str]:
    cats = set()
    for s in entry.get("senses", []):
        for c in s.get("categories", []):
            cats.add(c if isinstance(c, str) else c.get("name", ""))
    return cats


def link_target(sense):
    """활용형·이형 뜻이면 (kind, 원형)을 돌려준다."""
    for key, kind in (("form_of", "form"), ("alt_of", "alt")):
        for ref in sense.get(key) or []:
            target = (ref.get("word") or "").strip()
            if target:
                return kind, target
    return None


def qualifies(entry, senses) -> list[str]:
    """숙어로 넣는 이유. 빈 목록이면 숙어가 아니다.

    Wiktionary는 여러 단어 표제어를 뜻이 단어 뜻의 합이 아닐 때만 올린다(CFI). 그래서
    명사·고유명사가 아닌 여러 단어 표제어는 태그가 없어도 숙어로 본다 (hold dear,
    as well as). 명사는 대부분 복합명사(safety valve)라 숙어 표시가 있을 때만 넣는다.
    """
    pos = entry.get("pos")
    tags = {t for s in senses for t in s.get("tags") or []}
    why = []
    if "idiomatic" in tags:
        why.append("idiomatic")
    if "figuratively" in tags:
        why.append("figuratively")
    if any(PHRASAL_CAT.match(c) for c in categories(entry)):
        why.append("phrasal")
    if pos == "noun":
        if any(LITERAL_GLOSS in " ".join(s.get("glosses") or []) for s in senses):
            why.append("literal_sense")
    elif pos not in EXCLUDED_POS:
        why.append(f"pos:{pos}")
    return why


def level_of(why):
    """화면에서 무엇을 보여줄지 고르는 값. Wiktionary의 표시로 나눈다.

    idiom    숙어·비유 표시가 있다 (take for granted)
    phrasal  구동사 범주에 있다 (give up)
    phrase   그 밖의 고정 표현 (of course, small room). 문자 그대로 쓰인 경우가 많다
    """
    if "idiomatic" in why or "figuratively" in why:
        return "idiom"
    return "phrasal" if "phrasal" in why else "phrase"


def follow_links(word, next_hop, stop=()):
    """활용형·이형 연결을 원형까지 따라간다. stop에 닿으면 멈춘다.

    연결이 이어지기도 한다: pushed up the daisies → push up the daisies(이형) → push up daisies
    """
    for _ in range(4):
        if word in stop or word not in next_hop:
            break
        word = next_hop[word]
    return word


def gloss_of(sense) -> str:
    glosses = sense.get("glosses") or []
    if not glosses:
        return ""
    return glosses[-1] if len(glosses) > 1 else glosses[0]


def head_index(tokens, forms) -> int | None:
    """활용하는 단어의 위치. 활용형과 원형을 토큰별로 비교해서 다른 자리를 찾는다.

    활용형이 없으면 첫 단어로 본다 (동사 숙어는 대부분 동사로 시작한다).
    """
    for form_tokens in forms:
        if len(form_tokens) != len(tokens):
            continue
        diff = [i for i, (a, b) in enumerate(zip(tokens, form_tokens)) if a != b]
        if len(diff) == 1:
            return diff[0]
    return 0


def particle_like_words(conn):
    """동사 뒤에 와도 목적어가 앞에 낄 수 있는 말: Wiktionary 품사에 부사·전치사·형용사가 있고
    관사·한정사·대명사는 없는 한 단어 (up, into, dear — an, the, it, use는 아님)."""
    pos_of = defaultdict(set)
    for word, pos in conn.execute("SELECT word_normalized, pos FROM words WHERE word NOT LIKE '% %'"):
        pos_of[word].add(pos)
    return {w for w, ps in pos_of.items() if ps & OBJ_BEFORE_POS and not ps & NOMINAL_POS}


def compile_pattern(tokens, is_verb, forms, obj_ok):
    """표제어 토큰 → 패턴 (docs/idiom_detection.md §4.2).

    HEAD  활용하는 동사. lemma와 활용형으로 맞춘다
    LIT   고정 단어
    POSS  one's / someone's / somebody's
    NP    someone / somebody / something
    REFL  oneself
    OBJ   동사 바로 뒤의 목적어 자리 (opt). take [the cost] into account
    """
    head = head_index(tokens, forms) if is_verb else None
    out = []
    i = 0
    while i < len(tokens):
        t = tokens[i]
        nxt = tokens[i + 1] if i + 1 < len(tokens) else None
        if t in POSS_WORDS and nxt == "'s":
            out.append({"t": "POSS"})
            i += 2
            continue
        if i == head:
            head_forms = sorted({f[i] for f in forms if len(f) == len(tokens)} - {t})
            out.append({"t": "HEAD", "lemma": t, "forms": head_forms})
        elif t in NP_WORDS:
            out.append({"t": "NP"})
        elif t in REFL_WORDS:
            out.append({"t": "REFL"})
        else:
            out.append({"t": "LIT", "w": t})
        i += 1

    # 목적어 자리. Wiktionary의 transitive 태그는 빠진 항목이 많아서(take to task에도 없다)
    # 태그로 거르지 않는다. 실제로 목적어인지는 탐지기가 구문 분석으로 확인한다.
    # 두지 않는 경우:
    #   · 숙어에 이미 목적어 자리표시어가 있다 (make up one's mind)
    #   · 동사 다음 단어가 관사·명사 등이라 숙어 자신이 목적어를 가졌다 (keep an eye on, make use of)
    #   · 전치사로 끝난다 — 목적어는 맨 뒤에 온다 (look up to)
    hi = next((k for k, el in enumerate(out) if el["t"] == "HEAD"), None)
    last = out[-1]
    if (hi is not None and hi + 1 < len(out) and out[hi + 1]["t"] == "LIT"
            and obj_ok(out[hi + 1]["w"])
            and not any(el["t"] in ("POSS", "NP", "REFL") for el in out)
            and not (last["t"] == "LIT" and last["w"] in PREP_ONLY)):
        out.insert(hi + 1, {"t": "OBJ", "opt": True})
    return out


def fixed_keys(pattern):
    for el in pattern:
        if el["t"] == "HEAD":
            yield el["lemma"]
        elif el["t"] == "LIT":
            yield el["w"]


def scan(tokenize):
    """kaikki를 한 번 훑어서 원형 숙어와 그 활용형·이형을 모은다."""
    bases = []                      # 숙어 원형 항목
    links = []                      # (phrase, pos, kind, target) — 활용형·이형 항목
    excluded = set()                # 숙어 기준에 안 맞은 여러 단어 원형 (비교용)
    scanned = 0
    with open(KAIKKI, encoding="utf-8") as f:
        for line in f:
            scanned += 1
            if scanned % 300_000 == 0:
                print(f"  {scanned:>10,} scanned, {len(bases):,} idioms")
            entry = json.loads(line)
            word = apostrophe(entry.get("word", "").strip())
            if " " not in word or entry.get("lang_code", "en") != "en":
                continue
            senses = entry.get("senses") or []
            own = [s for s in senses if not link_target(s)]
            if not own:
                if senses:
                    kind, target = link_target(senses[0])
                    links.append((word, entry.get("pos"), kind, apostrophe(target)))
                continue
            why = qualifies(entry, own)
            if not why:
                excluded.add(normalize(word))
                continue

            forms = []
            for fm in entry.get("forms") or []:
                form = apostrophe(fm.get("form", "").strip())
                tags = set(fm.get("tags") or [])
                if " " in form and form != word and not tags & {"table-tags", "inflection-template"}:
                    forms.append((form, sorted(tags)))

            bases.append({
                "word": word,
                "pos": entry.get("pos"),
                "why": why,
                "tokens": [apostrophe(t.text.lower()) for t in tokenize(word)],
                "forms": forms,
                "senses": [{
                    "gloss": gloss_of(s),
                    "tags": s.get("tags") or [],
                    "literal": LITERAL_GLOSS in " ".join(s.get("glosses") or []),
                    "examples": [
                        (x["text"].strip(), x.get("type"))
                        for x in s.get("examples") or []
                        if x.get("text", "").strip() and not NYM_LINE.match(x["text"].strip())
                    ],
                } for s in own if gloss_of(s)],
            })
    print(f"  {scanned:,} scanned")
    return bases, links, excluded


def build(compare_samples=0):
    t0 = time.time()
    nlp = spacy.blank("en")
    tokenize = nlp.tokenizer

    print(f"Scanning {KAIKKI.name}...")
    bases, links, excluded = scan(tokenize)

    conn = sqlite3.connect(str(DB_PATH))
    c = conn.cursor()
    obj_ok = particle_like_words(conn).__contains__
    c.executescript("""
        DROP TABLE IF EXISTS idioms;
        DROP TABLE IF EXISTS idiom_senses;
        DROP TABLE IF EXISTS idiom_examples;
        DROP TABLE IF EXISTS idiom_forms;
        DROP TABLE IF EXISTS idiom_patterns;
        DROP TABLE IF EXISTS idiom_words;

        CREATE TABLE idioms (
            id                INTEGER PRIMARY KEY,
            phrase            TEXT NOT NULL,
            phrase_normalized TEXT NOT NULL,
            meaning           TEXT,
            pos               TEXT,
            included_by       TEXT,         -- idiomatic,phrasal,pos:verb … (숙어로 넣은 이유)
            level             TEXT NOT NULL -- idiom | phrasal | phrase (level_of)
        );
        CREATE TABLE idiom_senses (
            idiom_id  INTEGER NOT NULL REFERENCES idioms(id),
            sense_idx INTEGER NOT NULL,
            gloss     TEXT NOT NULL,
            tags      TEXT,                 -- JSON 배열
            literal   INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE idiom_examples (
            idiom_id  INTEGER NOT NULL REFERENCES idioms(id),
            sense_idx INTEGER NOT NULL,
            text      TEXT NOT NULL,
            type      TEXT                  -- example | quotation
        );
        CREATE TABLE idiom_forms (
            idiom_id        INTEGER NOT NULL REFERENCES idioms(id),
            form            TEXT NOT NULL,
            form_normalized TEXT NOT NULL,
            kind            TEXT NOT NULL,  -- form (활용형) | alt (이형)
            tags            TEXT
        );
        CREATE TABLE idiom_patterns (
            idiom_id INTEGER NOT NULL REFERENCES idioms(id),
            source   TEXT NOT NULL,         -- 패턴을 만든 표제 (원형 또는 이형)
            pattern  TEXT NOT NULL,         -- JSON. docs/idiom_detection.md §4.2
            anchor   TEXT NOT NULL,         -- 가장 드문 고정 단어 (후보 찾기 열쇠)
            n_fixed  INTEGER NOT NULL
        );
        CREATE TABLE idiom_words (
            idiom_id INTEGER NOT NULL REFERENCES idioms(id),
            word     TEXT NOT NULL,         -- 고정 단어. 동사는 원형
            position INTEGER NOT NULL       -- 숙어 안의 순서 (어순 비교용)
        );
    """)

    by_phrase = defaultdict(list)    # 정규형 → idiom id들
    idiom_rows, sense_rows, example_rows, form_rows = [], [], [], []
    pattern_src = []                 # (idiom_id, source, pattern)
    for iid, b in enumerate(bases, 1):
        idiom_gloss = next((s["gloss"] for s in b["senses"] if not s["literal"]), None)
        meaning = idiom_gloss or (b["senses"][0]["gloss"] if b["senses"] else "")
        idiom_rows.append((iid, b["word"], normalize(b["word"]), meaning, b["pos"], ",".join(b["why"]),
                           level_of(b["why"])))
        by_phrase[normalize(b["word"])].append(iid)
        for si, s in enumerate(b["senses"], 1):
            sense_rows.append((iid, si, s["gloss"], json.dumps(s["tags"]), int(s["literal"])))
            example_rows.extend((iid, si, text, typ) for text, typ in s["examples"])
        form_token_lists = []
        for form, tags in b["forms"]:
            form_rows.append((iid, form, normalize(form), "form", " ".join(tags) or None))
            form_token_lists.append([apostrophe(t.text.lower()) for t in tokenize(form)])
        b["form_tokens"] = form_token_lists
        pattern_src.append((iid, b["word"], compile_pattern(b["tokens"], b["pos"] == "verb", form_token_lists, obj_ok)))

    # 활용형·이형 항목을 원형에 붙인다. 이형은 어순이 달라서(pull up one's socks) 패턴도 만든다
    next_hop = {normalize(p): normalize(t) for p, _, _, t in links}
    orphan = Counter()
    known_forms = {(r[0], r[2]) for r in form_rows}
    for phrase, pos, kind, target in links:
        base = follow_links(normalize(target), next_hop, stop=by_phrase)
        ids = by_phrase.get(base)
        if not ids:
            if base not in excluded:     # 원형이 숙어가 아닌 경우(복합명사 복수형 등)는 세지 않는다
                orphan[kind] += 1
            continue
        iid = ids[0]
        if (iid, normalize(phrase)) not in known_forms:
            form_rows.append((iid, phrase, normalize(phrase), kind, None))
            known_forms.add((iid, normalize(phrase)))
        if kind == "alt":
            tokens = [apostrophe(t.text.lower()) for t in tokenize(phrase)]
            pattern_src.append((iid, phrase, compile_pattern(tokens, pos == "verb", [], obj_ok)))

    # 열쇠: 패턴 전체에서 가장 적게 나오는 고정 단어. 같으면 긴 단어
    key_count = Counter(k for _, _, p in pattern_src for k in set(fixed_keys(p)))
    pattern_rows = []
    word_rows = set()
    for iid, source, p in pattern_src:
        keys = list(fixed_keys(p))
        if not keys:
            continue
        word_rows.update((iid, w, i) for i, w in enumerate(keys) if any(ch.isalnum() for ch in w))
        anchor = min(keys, key=lambda k: (key_count[k], -len(k)))
        pattern_rows.append((iid, source, json.dumps(p, ensure_ascii=False), anchor, len(keys)))

    c.executemany("INSERT INTO idioms VALUES (?,?,?,?,?,?,?)", idiom_rows)
    c.executemany("INSERT INTO idiom_senses VALUES (?,?,?,?,?)", sense_rows)
    c.executemany("INSERT INTO idiom_examples VALUES (?,?,?,?)", example_rows)
    c.executemany("INSERT INTO idiom_forms VALUES (?,?,?,?,?)", form_rows)
    c.executemany("INSERT INTO idiom_patterns VALUES (?,?,?,?,?)", pattern_rows)
    c.executemany("INSERT INTO idiom_words VALUES (?,?,?)", sorted(word_rows))
    c.executescript("""
        CREATE INDEX idx_idioms_normalized ON idioms(phrase_normalized);
        CREATE INDEX idx_idiom_senses ON idiom_senses(idiom_id);
        CREATE INDEX idx_idiom_examples ON idiom_examples(idiom_id);
        CREATE INDEX idx_idiom_forms_normalized ON idiom_forms(form_normalized);
        CREATE INDEX idx_idiom_patterns_anchor ON idiom_patterns(anchor);
        CREATE INDEX idx_idiom_words_word ON idiom_words(word);
        CREATE INDEX idx_idiom_words_idiom ON idiom_words(idiom_id);
    """)
    conn.commit()

    why = Counter(w for b in bases for w in b["why"])
    print(f"  idioms: {len(idiom_rows):,}  넣은 이유(겹침): " + " · ".join(f"{k} {v:,}" for k, v in why.most_common()))
    print(f"  senses: {len(sense_rows):,} (literal {sum(r[4] for r in sense_rows):,}), "
          f"examples: {len(example_rows):,}")
    print(f"  forms: {len(form_rows):,}, 원형 항목이 kaikki에 없는 활용형·이형: "
          + ", ".join(f"{k} {v:,}" for k, v in orphan.items()))
    slots = Counter(el["t"] for _, _, p in pattern_src for el in p)
    print(f"  patterns: {len(pattern_rows):,}  슬롯: " + " · ".join(f"{k} {v:,}" for k, v in slots.most_common()))

    if OLD_IDIOMS.exists():
        compare(c, excluded, next_hop, compare_samples)
    conn.close()
    print(f"\nDone in {time.time() - t0:.0f}s")


def compare(c, excluded, next_hop, samples):
    """옛 english_idioms.json(69,651)과 비교한다. 옛 목록의 항목이 어디로 갔는지."""
    with open(OLD_IDIOMS, encoding="utf-8") as f:
        old = {normalize(apostrophe(e["word"])) for e in json.load(f)}
    new_base = {r[0] for r in c.execute("SELECT phrase_normalized FROM idioms")}
    new_forms = {r[0] for r in c.execute("SELECT form_normalized FROM idiom_forms")}
    rest = old - new_base - new_forms
    as_link = {w for w in rest if w in next_hop}
    groups = {
        "원형으로 들어감": old & new_base,
        "활용형·이형으로 붙음": (old - new_base) & new_forms,
        "숙어 기준에서 빠짐": rest & excluded,
        "원형이 기준에서 빠진 활용형": {w for w in as_link if follow_links(w, next_hop) in excluded},
        "원형이 kaikki에 없는 활용형": {w for w in as_link if follow_links(w, next_hop) not in excluded},
        "kaikki에 없음": rest - excluded - as_link,
    }
    print(f"\n옛 english_idioms.json {len(old):,}개 (정규형 기준)")
    for name, items in groups.items():
        print(f"  {name:16} {len(items):>7,}")
        if samples:
            print("    " + " | ".join(sorted(items)[:: max(1, len(items) // samples)][:samples]))
    added = new_base - old
    print(f"새로 들어온 숙어 원형 {len(added):,}개")
    if samples:
        print("    " + " | ".join(sorted(added)[:: max(1, len(added) // samples)][:samples]))


def check(phrases):
    conn = sqlite3.connect(str(DB_PATH))
    for phrase in phrases:
        norm = normalize(apostrophe(phrase))
        rows = conn.execute("""
            SELECT id, phrase, pos, included_by FROM idioms WHERE phrase_normalized = ?
            UNION
            SELECT i.id, i.phrase, i.pos, i.included_by FROM idiom_forms f JOIN idioms i ON i.id = f.idiom_id
            WHERE f.form_normalized = ?""", (norm, norm)).fetchall()
        print(f"=== {phrase}" + ("" if rows else "  (없음)"))
        for iid, p, pos, by in rows:
            print(f"  [{iid}] {p} ({pos}; {by})")
            for si, gloss, tags, lit in conn.execute(
                    "SELECT sense_idx, gloss, tags, literal FROM idiom_senses WHERE idiom_id=?", (iid,)):
                print(f"    {si}. {'(literal) ' if lit else ''}{gloss[:90]}  {json.loads(tags)}")
            for source, pattern, anchor in conn.execute(
                    "SELECT source, pattern, anchor FROM idiom_patterns WHERE idiom_id=?", (iid,)):
                els = " ".join(el.get("w") or el.get("lemma") or el["t"] if el["t"] in ("LIT", "HEAD")
                               else f"[{el['t']}{'?' if el.get('opt') else ''}]" for el in json.loads(pattern))
                print(f"    pattern ({source}): {els}   anchor={anchor}")
    conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--compare", action="store_true", help="옛 목록과의 차이를 예시와 함께 보여준다")
    parser.add_argument("--check", nargs="+", metavar="PHRASE")
    args = parser.parse_args()
    if args.check:
        check(args.check)
    else:
        build(compare_samples=12 if args.compare else 0)
