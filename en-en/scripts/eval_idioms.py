#!/usr/bin/env python3
"""숙어 탐지기를 kaikki 예문으로 평가한다 (docs/idiom_detection.md §6).

    python en-en/scripts/eval_idioms.py --sets                  # 평가 세트 크기와 예시만
    python en-en/scripts/eval_idioms.py                         # idiom_detect.py
    python en-en/scripts/eval_idioms.py --detector v2           # reading의 v2 (기준선)
    python en-en/scripts/eval_idioms.py --detector v2 --limit 3000 --misses 15
    python en-en/scripts/eval_idioms.py --book <book_package.json>   # 정밀도 검토용 샘플

정답은 손으로 만들지 않는다. 예문 하나마다 "그 예문이 붙은 숙어를 찾았는가"를 본다.
예문은 숙어의 고정 단어(HEAD·LIT)와 맞춰서 나눈다:

  연속        고정 단어가 붙어 있다        took into account
  자리표시어  one's·someone 자리가 채워졌다  made up his mind
  불연속      동사 숙어의 고정 단어 사이에 말이 끼었다  put him off
  문자 그대로 문자 그대로의 뜻에 붙은 예문    look up at the stars (숙어로 잡으면 안 좋다)
  제외        고정 단어가 다 없다 (변형·잡음)  drier than a dead dingo's donger

구문 분석 결과는 data/build/eval_docs_<모델>.spacy에 저장해 두고 다시 쓴다.
"""

import argparse
import importlib.util
import json
import os
import random
import sqlite3
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import spacy
from spacy.tokens import DocBin

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_idioms import DB_PATH, apostrophe  # noqa: E402
from build_dict_db import normalize  # noqa: E402

GUTENBERG = Path(os.environ.get("MARGINALIA_GUTENBERG", Path.home() / "reading" / "gutenberg"))
MAX_GAP = 6          # 고정 단어 사이가 이보다 멀면 우연으로 본다
SETS = ("연속", "자리표시어", "불연속", "문자 그대로")

# docs/idiom_detection.md §6의 회귀 사례: (문장, 찾아야 할 숙어, 나오면 안 되는 숙어)
REGRESSION = [
    ("She took the cost into account.", {"take into account"}, set()),
    ("He looked the word up.", {"look up"}, {"word up"}),
    ("I looked it up in the dictionary.", {"look up"}, set()),
    ("He made up his mind at last.", {"make up one's mind"}, {"make up"}),
    ("Keep a close eye on him.", {"keep an eye on"}, set()),
    ("Turn the light off.", {"turn off"}, {"light off"}),
    ("He gave it up.", {"give up"}, set()),
    ("They took the rumour for granted.", {"take for granted"}, set()),
    ("Bear these facts in mind.", {"bear in mind"}, set()),
    ("He picked the heavy book up from the floor.", {"pick up"}, {"book up"}),
    ("She looked up the street.", set(), {"look up"}),
]


def tokens_of(tokenizer, text):
    """문장 부호는 뺀다. warts-and-all, "through the mill"은 붙어 있는 것으로 친다."""
    return [apostrophe(t.text.lower()) for t in tokenizer(text) if not t.is_punct]


def fixed_matchers(pattern, head_forms):
    """패턴의 고정 단어마다 맞는 소문자 형태 집합."""
    out = []
    for el in pattern:
        if el["t"] == "HEAD":
            out.append({el["lemma"], *el["forms"], *head_forms})
        elif el["t"] == "LIT" and any(ch.isalnum() for ch in el["w"]):
            out.append({el["w"]})
    return out


def best_gap(tokens, matchers):
    """고정 단어를 순서대로 찾아서 가장 벌어진 간격이 제일 작은 경우의 간격. 없으면 None."""
    where = defaultdict(list)
    for i, t in enumerate(tokens):
        where[t].append(i)
    positions = [sorted(i for form in m for i in where.get(form, ())) for m in matchers]
    if not all(positions):
        return None
    best = None
    for start in positions[0]:
        prev, widest = start, 0
        for pos in positions[1:]:
            nxt = next((i for i in pos if i > prev), None)
            if nxt is None:
                widest = None
                break
            widest = max(widest, nxt - prev - 1)
            prev = nxt
        if widest is not None and (best is None or widest < best):
            best = widest
    return best


def has_sequence(tokens, seq):
    n = len(seq)
    return any(tokens[i:i + n] == seq for i in range(len(tokens) - n + 1))


def classify(tokens, patterns, forms):
    """예문을 세트로 나눈다. patterns: [(패턴, 고정 단어 형태들)], forms: 활용형 토큰 열 (red flags)."""
    kinds = []
    if any(has_sequence(tokens, f) for f in forms):
        return "연속"
    for pattern, matchers in patterns:
        gap = best_gap(tokens, matchers)
        if gap is None or gap > MAX_GAP:
            continue
        if gap == 0:
            kinds.append("연속")
        elif any(el["t"] in ("POSS", "NP", "REFL") for el in pattern):
            kinds.append("자리표시어")
        elif any(el["t"] == "HEAD" for el in pattern):
            kinds.append("불연속")      # 불연속은 동사 숙어에만 있다. 나머지는 우연히 벌어진 것
    for kind in ("연속", "자리표시어", "불연속"):
        if kind in kinds:
            return kind
    return "제외"


def load_examples(tokenizer):
    """예문을 읽어서 세트를 정한다."""
    conn = sqlite3.connect(str(DB_PATH))
    idioms = {r[0]: {"id": r[0], "phrase": r[1], "norm": r[2], "pos": r[3]}
              for r in conn.execute("SELECT id, phrase, phrase_normalized, pos FROM idioms")}

    names = defaultdict(set)         # 이 숙어로 쳐 주는 이름 (원형 + 활용형 + 이형)
    forms = defaultdict(list)
    for iid, idiom in idioms.items():
        names[iid].add(idiom["norm"])
    for iid, form in conn.execute("SELECT idiom_id, form_normalized FROM idiom_forms"):
        names[iid].add(form)
        forms[iid].append(tokens_of(tokenizer, form))

    raw_patterns = defaultdict(list)
    head_forms = defaultdict(set)
    for iid, pattern in conn.execute("SELECT idiom_id, pattern FROM idiom_patterns"):
        p = json.loads(pattern)
        raw_patterns[iid].append(p)
        for el in p:
            if el["t"] == "HEAD":
                head_forms[iid].update(el["forms"])
    patterns = {iid: [(p, fixed_matchers(p, head_forms[iid])) for p in ps]
                for iid, ps in raw_patterns.items()}

    examples, seen = [], set()
    for iid, text, literal in conn.execute("""
            SELECT e.idiom_id, e.text, s.literal FROM idiom_examples e
            JOIN idiom_senses s ON s.idiom_id = e.idiom_id AND s.sense_idx = e.sense_idx
            ORDER BY e.rowid"""):
        if (iid, text) in seen or iid not in patterns:
            continue
        seen.add((iid, text))
        kind = classify(tokens_of(tokenizer, text), patterns[iid], forms[iid])
        if literal and kind != "제외":
            kind = "문자 그대로"
        examples.append({"idiom": iid, "text": text, "set": kind})
    conn.close()
    return examples, idioms, names


def parsed_docs(nlp, examples, model, use_cache):
    """예문 구문 분석. 전체를 돌릴 때는 파일에 저장해 두고 다시 쓴다."""
    texts = [e["text"] for e in examples]
    cache = DB_PATH.parent / f"eval_docs_{model}.spacy"
    if use_cache and cache.exists():
        docs = list(DocBin().from_disk(cache).get_docs(nlp.vocab))
        if [d.text for d in docs] == texts:
            print(f"  구문 분석 결과 재사용: {cache.name}")
            return docs
    t0 = time.time()
    docs = []
    for i, doc in enumerate(nlp.pipe(texts, batch_size=256), 1):
        docs.append(doc)
        if i % 10000 == 0:
            print(f"  {i:,}/{len(texts):,} 구문 분석 ({time.time() - t0:.0f}s)", flush=True)
    if use_cache:
        DocBin(store_user_data=False, docs=docs).to_disk(cache)
    return docs


class V2Detector:
    """reading의 extract_english_idioms_v2.py를 그대로 돌린다 (기준선)."""
    name = "v2"

    def __init__(self, nlp):
        path = GUTENBERG / "extract_english_idioms_v2.py"
        spec = importlib.util.spec_from_file_location("extract_english_idioms_v2", path)
        self.v2 = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.v2)
        phrasal, frames = self.v2.load_phrasal_verbs(), self.v2.load_fixed_frames()
        self.known = set(phrasal) | set(frames)
        self.matcher, self.info = self.v2.build_matcher(nlp, phrasal, frames, "both")
        self.vocab = nlp.vocab
        self.doc = None

    def __call__(self, text):
        return self.doc      # scan_sentences가 nlp(text)로 부르는 자리. 이미 분석한 Doc을 돌려준다

    def detect(self, doc):
        self.doc = doc
        found = self.v2.scan_sentences(self, self.matcher, self.info, [{"id": 0, "text": doc.text}])
        return {r["idiom"] for r in found}

    def covers(self, idiom):
        return idiom["norm"] in self.known


class NewDetector:
    """en-en/app/idiom_detect.py."""
    name = "new"

    def __init__(self, nlp):
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
        from idiom_detect import IdiomDetector
        self.detector = IdiomDetector(db_path=DB_PATH, nlp=nlp)

    def detect(self, doc):
        return {normalize(apostrophe(r["idiom"])) for r in self.detector.detect(doc)}

    def covers(self, idiom):
        return idiom["id"] in self.detector.active


DETECTORS = {"v2": V2Detector, "new": NewDetector}


def show_sets(examples, idioms, samples):
    count = Counter(e["set"] for e in examples)
    print(f"\n예문 {len(examples):,}개")
    rng = random.Random(0)
    for kind in (*SETS, "제외"):
        items = [e for e in examples if e["set"] == kind]
        print(f"  {kind:8} {count[kind]:>7,}")
        for e in rng.sample(items, min(samples, len(items))):
            print(f"      [{idioms[e['idiom']]['phrase']}] {e['text'][:100]}")


def run_regression(nlp, detector):
    print("\n회귀 사례")
    passed = 0
    for text, want, forbid in REGRESSION:
        found = detector.detect(nlp(text))
        ok = want <= found and not (forbid & found)
        passed += ok
        print(f"  {'✅' if ok else '❌'} {text:46} {sorted(found)}")
    print(f"  {passed}/{len(REGRESSION)} 통과")
    return passed


def evaluate(detector, docs, examples, idioms, names, misses, extras):
    t0 = time.time()
    stats = defaultdict(Counter)
    extra = 0
    extra_count = Counter()
    missed = defaultdict(list)
    used = 0
    for doc, e in zip(docs, examples):
        if e["set"] == "제외":
            continue
        used += 1
        found = detector.detect(doc)
        gold = names[e["idiom"]]
        hit = bool(found & gold)
        extra += len(found - gold)
        extra_count.update(found - gold)
        row = stats[e["set"]]
        row["n"] += 1
        row["hit"] += hit
        if detector.covers(idioms[e["idiom"]]):
            row["n_in"] += 1
            row["hit_in"] += hit
        if not hit:
            missed[e["set"]].append(e)
        if used % 10000 == 0:
            print(f"  {used:,}개 평가 ({time.time() - t0:.0f}s)", flush=True)

    print(f"\n{detector.name} 결과 (탐지기가 아는 숙어 = 범위 안)")
    print(f"  {'세트':10} {'예문':>7} {'찾음':>7} {'재현율':>7}   {'범위 안':>7} {'찾음':>7} {'재현율':>7}")
    for kind in SETS:
        r = stats[kind]
        rate = r["hit"] / r["n"] if r["n"] else 0
        rate_in = r["hit_in"] / r["n_in"] if r["n_in"] else 0
        print(f"  {kind:10} {r['n']:>7,} {r['hit']:>7,} {rate:>7.1%}   {r['n_in']:>7,} {r['hit_in']:>7,} {rate_in:>7.1%}")
    print(f"  예문당 다른 숙어 탐지: {extra / max(used, 1):.2f}개  (맞는 것도 섞여 있다. 많으면 오탐을 의심한다)")
    print(f"  ({time.time() - t0:.0f}s)")

    if extras:
        print(f"\n가장 많이 잡힌 다른 숙어 (예문의 숙어가 아닌 것): 종류 {len(extra_count):,}")
        print("  " + " · ".join(f"{k} {v}" for k, v in extra_count.most_common(extras)))

    if misses:
        rng = random.Random(0)
        for kind in SETS[:3]:
            print(f"\n못 찾은 {kind} 예시")
            for e in rng.sample(missed[kind], min(misses, len(missed[kind]))):
                print(f"  [{idioms[e['idiom']]['phrase']}] {e['text'][:110]}")
    return stats


def book_sample(nlp, book, sample, out, levels, seed):
    """책 문장의 탐지 결과를 무작위로 뽑아 사람이 볼 파일을 만든다 (정밀도는 정답이 없다).

    붙어 있는 것과 떨어진 것을 반씩 뽑는다. 떨어진 쪽이 오탐 위험이 크고 수가 적기 때문이다.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
    from idiom_detect import IdiomDetector
    detector = IdiomDetector(db_path=DB_PATH, nlp=nlp)
    with open(book, encoding="utf-8") as f:
        sentences = [(s["id"], s["text"]) for ch in json.load(f)["chapters"] for s in ch["sentences"]]
    hits = []
    for (sid, _), doc in zip(sentences, nlp.pipe((t for _, t in sentences), batch_size=256)):
        hits.extend({**r, "sid": sid, "text": doc.text} for r in detector.detect(doc) if r["level"] in levels)
    split = [h for h in hits if not h["continuous"]]
    joined = [h for h in hits if h["continuous"]]
    print(f"문장 {len(sentences):,}개에서 {len(hits):,}개 탐지 (붙음 {len(joined):,} · 떨어짐 {len(split):,})")
    rng = random.Random(seed)
    half = sample // 2
    picked = rng.sample(split, min(half, len(split))) + rng.sample(joined, min(sample - half, len(joined)))
    with open(out, "w", encoding="utf-8") as f:
        f.write("판정\t숙어\t찾은 말\t구분\t문장 id\t문장\n")
        for h in picked:
            f.write(f"\t{h['idiom']}\t{h['as_found']}\t{'붙음' if h['continuous'] else '떨어짐'}\t{h['sid']}\t{h['text']}\n")
    print(f"검토 파일: {out} ({len(picked)}개)")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--detector", choices=sorted(DETECTORS), default="new")
    parser.add_argument("--model", default="en_core_web_sm")
    parser.add_argument("--sets", action="store_true", help="평가 세트만 보여준다")
    parser.add_argument("--limit", type=int, help="예문을 무작위로 이만큼만 쓴다")
    parser.add_argument("--misses", type=int, default=0, help="못 찾은 예문을 세트마다 이만큼 보여준다")
    parser.add_argument("--book", help="book_package.json. 탐지 결과 샘플을 --out에 쓴다")
    parser.add_argument("--sample", type=int, default=200)
    parser.add_argument("--levels", default="idiom,phrasal", help="샘플에 넣을 level (화면 기본값과 같게)")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--out", default=str(DB_PATH.parent / "idiom_review.tsv"))
    parser.add_argument("--extras", type=int, default=0, help="예문의 숙어가 아닌데 많이 잡힌 숙어를 이만큼 보여준다")
    args = parser.parse_args()

    if args.book:
        book_sample(spacy.load(args.model), args.book, args.sample, args.out, args.levels.split(","), args.seed)
        return

    tokenizer = spacy.blank("en").tokenizer
    examples, idioms, names = load_examples(tokenizer)
    if args.sets:
        show_sets(examples, idioms, 6)
        return
    print(f"예문 {len(examples):,}개: " + " · ".join(f"{k} {v:,}" for k, v in Counter(e["set"] for e in examples).most_common()))

    if args.limit:
        examples = random.Random(0).sample(examples, min(args.limit, len(examples)))
    nlp = spacy.load(args.model)
    detector = DETECTORS[args.detector](nlp)
    run_regression(nlp, detector)
    docs = parsed_docs(nlp, examples, args.model, use_cache=not args.limit)
    evaluate(detector, docs, examples, idioms, names, args.misses, args.extras)


if __name__ == "__main__":
    main()
