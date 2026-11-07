#!/usr/bin/env python3
"""문장 속 숙어를 찾는다. 숙어 단어 사이에 다른 말이 끼어 있어도 찾는다.

    python en-en/app/idiom_detect.py --text "She took the cost into account."

설계는 docs/idiom_detection.md §4. 패턴은 build_idioms.py가 dict.db에 만든 idiom_patterns다.

v2(reading의 extract_english_idioms_v2.py)는 끼는 말을 "토큰 0~2개"로 제한했다.
여기서는 끼는 말이 문법으로 설명되는지를 본다:
  · OBJ   동사의 목적어 하나 (하위 트리 전체라서 길이 제한이 거의 없다)
  · POSS  소유격 / NP 명사구 / REFL 재귀대명사
  · 그 밖 숙어 단어를 꾸미는 말 (keep a close eye on)
그래도 못 맞춘 동사 숙어는 구문 트리로 한 번 더 찾는다 (_catena).
같은 토큰을 쓰는 매칭이 여럿이면 고정 단어가 많은 쪽을 남긴다 (make up < make up one's mind).

서버(Docker)는 en-en/app의 파일만 복사하므로 이 파일은 app에 둔다.
"""

import argparse
import json
import os
import sqlite3
from collections import defaultdict
from pathlib import Path

import spacy
from spacy.lang.en.stop_words import STOP_WORDS

DEFAULT_DB = Path(__file__).resolve().parent.parent / "data" / "build" / "dict.db"

MOD_DEPS = {"amod", "advmod"}
OBJ_DEPS = {"dobj", "dative", "nsubj", "nsubjpass", "attr", "oprd", "obj"}
NOUN_LIKE = {"NOUN", "PROPN", "PRON", "NUM"}
REFLEXIVES = {"myself", "yourself", "himself", "herself", "itself", "oneself",
              "ourselves", "yourselves", "themselves", "themself"}
AUX_LEMMAS = {"be", "have", "do"}
# 트리를 따라갈 때 건너지 않는 관계. 숙어 단어가 이런 관계로 이어지지는 않는다
# (care to walk, and for / saw your wife the other day)
NOT_IDIOM_LINK = {"conj", "cc", "npadvmod", "advcl", "relcl", "acl", "appos", "parataxis"}
ARTICLES = {"a", "an"}      # keep an eye on → keep a close eye on
HYPHENS_QUOTES = {"-", "–", "—", '"', "'", "“", "”", "‘", "’", "`", "``", "''"}
COMMA_OK_POS = {"intj", "phrase", "proverb"}     # oh, yeah / drive for show, putt for dough

MAX_SLOT_GAP = 12      # 자리(OBJ·NP·POSS)에 들어가는 말의 최대 길이
MAX_MOD_GAP = 3        # 수식어만 낄 때의 최대 길이


def apostrophe(text):
    return text.replace("’", "'")


class Pattern:
    __slots__ = ("idiom_id", "phrase", "norm", "pos", "n_fixed", "steps", "lead", "trail",
                 "intransitive_only", "fixed", "level")

    def __init__(self, row, elements):
        (self.idiom_id, self.phrase, self.norm, self.pos, self.n_fixed,
         self.intransitive_only, self.level) = row
        self.steps = []          # [(고정 원소, 그 앞의 자리)]
        self.lead = None         # 첫 고정 단어 앞의 자리
        self.trail = None        # 마지막 고정 단어 뒤의 자리
        slot = None
        for el in elements:
            t = el["t"]
            if t in ("HEAD", "LIT"):
                if t == "LIT" and not any(ch.isalnum() for ch in el["w"]):
                    continue     # 문장 부호는 고정 단어로 치지 않는다
                if not self.steps:
                    self.lead, slot = slot, None
                if t == "HEAD":
                    el = {**el, "forms": set(el["forms"])}
                self.steps.append((el, slot))
                slot = None
            else:
                slot = t
        self.trail = slot
        self.fixed = [el.get("w") or el["lemma"] for el, _ in self.steps]
        # 동사가 아닌 소유격 숙어는 문자 그대로 쓰일 때가 많다 (in his eyes, in his pocket, at his feet).
        # to my mind 같은 좋은 숙어와 태그로 구별되지 않아서 전부 기본 화면에서 뺀다. 검색에는 나온다
        if self.pos != "verb" and "POSS" in (self.lead, self.trail, *(s for _, s in self.steps)):
            self.level = "phrase"


def too_weak(pat, idiomatic):
    """Wiktionary에는 있지만 문장에서 숙어로 표시할 수 없는 패턴.

    · 기능어만으로 된 말: out of, up to, all that
    · be·have·do가 조동사처럼 쓰이는 말: there be, have in, be on, do it, be right
    · 고정 단어가 너무 약한 자리표시어 패턴: piece of [NP], take [NP] to
    """
    all_stop = all(w in STOP_WORDS for w in pat.fixed)
    head = next((el["lemma"] for el, _ in pat.steps if el["t"] == "HEAD"), None)
    if pat.pos != "verb" and all_stop:
        return True
    if head in AUX_LEMMAS or "be" in pat.fixed[:2] and head is None:
        if all_stop or (len(pat.fixed) == 2 and not idiomatic):
            return True
    has_np = pat.trail == "NP" or any(slot == "NP" for _, slot in pat.steps)
    if has_np and (all_stop or (pat.pos != "verb" and len(pat.fixed) <= 2)):
        return True
    return False


class View:
    """Doc을 한 번 훑어서 비교할 값을 준비해 둔다."""

    def __init__(self, doc):
        self.doc = doc
        self.lower = [apostrophe(t.lower_) for t in doc]
        self.lemma = [apostrophe(t.lemma_.lower()) for t in doc]
        self.sent_end = [0] * len(doc)
        for sent in doc.sents:
            for i in range(sent.start, sent.end):
                self.sent_end[i] = sent.end
        self.where = defaultdict(list)
        for i, (lo, le) in enumerate(zip(self.lower, self.lemma)):
            self.where[lo].append(i)
            if le != lo:
                self.where[le].append(i)


class IdiomDetector:
    def __init__(self, db_path=None, nlp=None, keep_function_phrases=False):
        self.nlp = nlp
        self.by_anchor = defaultdict(list)
        self.active = set()      # 탐지 대상 숙어 id (too_weak로 뺀 것 제외)
        self.senses_db = str(db_path or os.environ.get("DICT_DB_PATH") or DEFAULT_DB)
        conn = sqlite3.connect(self.senses_db)
        # 뜻 태그가 intransitive뿐인 숙어 (전치사 + 목적어가 따라오면 숙어가 아니다: come in the house)
        transitive = {r[0] for r in conn.execute(
            "SELECT DISTINCT idiom_id FROM idiom_senses WHERE tags LIKE '%\"transitive\"%'")}
        intransitive = {r[0] for r in conn.execute(
            "SELECT DISTINCT idiom_id FROM idiom_senses WHERE tags LIKE '%\"intransitive\"%'")}
        idiomatic = {r[0] for r in conn.execute(
            "SELECT DISTINCT idiom_id FROM idiom_senses WHERE tags LIKE '%\"idiomatic\"%'")}
        for iid, phrase, norm, pos, pattern, anchor, n_fixed, level in conn.execute("""
                SELECT i.id, i.phrase, i.phrase_normalized, i.pos, p.pattern, p.anchor, p.n_fixed, i.level
                FROM idiom_patterns p JOIN idioms i ON i.id = p.idiom_id"""):
            p = Pattern((iid, phrase, norm, pos, n_fixed, iid in intransitive and iid not in transitive,
                         level), json.loads(pattern))
            if len(p.steps) < 2 or (not keep_function_phrases and too_weak(p, iid in idiomatic)):
                continue
            self.by_anchor[anchor].append(p)
            self.active.add(iid)
        conn.close()

    # --- 토큰 맞추기 ---

    @staticmethod
    def _fixed_at(view, i, el):
        tok = view.doc[i]
        if el["t"] == "LIT":
            w, low = el["w"], view.lower[i]
            return (low == w or (w in ARTICLES and low in ARTICLES)
                    or (tok.tag_ in ("NNS", "NNPS") and view.lemma[i] == w))
        if tok.pos_ not in ("VERB", "AUX") and not tok.tag_.startswith("VB"):
            return False
        return view.lemma[i] == el["lemma"] or view.lower[i] == el["lemma"] or view.lower[i] in el["forms"]

    @staticmethod
    def _gap_ok(view, slot, gap, head_i, next_i, matched, is_verb):
        """gap(토큰 위치 목록)이 자리 slot으로 설명되는가."""
        if not gap:
            return slot in (None, "OBJ")
        if slot is None and not is_verb:
            return False         # 불연속은 동사 숙어에만 있다 (on one occasion은 on occasion이 아니다)
        doc = view.doc
        gap_set = set(gap)
        if slot == "REFL":
            return len(gap) == 1 and view.lower[gap[0]] in REFLEXIVES
        anchors = set(matched) | {next_i}
        rest = []
        for i in gap:
            t = doc[i]
            if t.head.i in gap_set and t.head.i != i:
                continue
            if t.dep_ in MOD_DEPS and t.head.i in anchors and not (slot == "POSS" and t.dep_ == "poss"):
                continue         # 숙어 단어를 꾸미는 말
            rest.append(t)
        if slot is None:
            return not rest and len(gap) <= MAX_MOD_GAP
        if len(gap) > MAX_SLOT_GAP:
            return False
        if slot == "OBJ":
            if not rest:
                return True
            if len(rest) != 1:
                return False
            t = rest[0]
            return (t.pos_ in NOUN_LIKE and t.dep_ in OBJ_DEPS
                    and t.head.i in (head_i, next_i))
        if len(rest) != 1:
            return False
        t = rest[0]
        if slot == "POSS":
            return t.tag_ == "PRP$" or t.dep_ == "poss"
        return t.pos_ in NOUN_LIKE      # NP

    def _align(self, view, pat):
        """패턴을 맞출 수 있는 토큰 위치 목록들을 돌려준다."""
        steps = pat.steps
        results = []
        comma_ok = pat.pos in COMMA_OK_POS

        def transparent(i):
            text = view.doc[i].text
            return text in HYPHENS_QUOTES or (comma_ok and text == ",")

        def walk(k, matched):
            if k == len(steps):
                results.append(list(matched))
                return
            el, slot = steps[k]
            last = matched[-1]
            head_i = next((m for m, (e, _) in zip(matched, steps) if e["t"] == "HEAD"), last)
            limit = min(view.sent_end[last], last + MAX_SLOT_GAP + 2)
            for i in range(last + 1, limit):
                if self._fixed_at(view, i, el):
                    gap = [g for g in range(last + 1, i) if not transparent(g)]
                    if self._gap_ok(view, slot, gap, head_i, i, matched, pat.pos == "verb"):
                        walk(k + 1, matched + [i])
                        if results:
                            return

        first = steps[0][0]
        key = first.get("w") or first["lemma"]
        candidates = set(view.where.get(key, ()))
        if first["t"] == "HEAD":
            for form in first["forms"]:
                candidates.update(view.where.get(form, ()))
        for start in sorted(candidates):
            if self._fixed_at(view, start, first):
                walk(1, [start])
                if results:
                    break
        return results

    def _catena(self, view, pat):
        """동사에서 시작해 구문 트리를 부모-자식으로 끊기지 않고 고정 단어를 다 모은다.

        숙어 단어는 트리에서 이어져 있다(catena). 그래서 give you pause, keep my house처럼
        자리 규칙에 없는 말이 끼어도 찾는다. 이어져 있어야 하므로 went up to the attic의
        to는 go에 닿지 않는다 (to는 up에 붙어 있다). 자리표시어가 있는 숙어는 하지 않는다:
        ring the bell은 ring someone's bell이 아니다.
        """
        if pat.pos != "verb" or pat.lead or pat.trail or any(
                slot in ("POSS", "NP", "REFL") for _, slot in pat.steps):
            return None
        head = next((el for el, _ in pat.steps if el["t"] == "HEAD"), None)
        if head is None or pat.steps[0][0] is not head:
            return None
        rest0 = [el for el, _ in pat.steps[1:]]
        for i in sorted({i for k in (head["lemma"], *head["forms"]) for i in view.where.get(k, ())}):
            if not self._fixed_at(view, i, head):
                continue
            rest, got = list(rest0), [view.doc[i]]
            grew = True
            while rest and grew:
                grew = False
                for g in list(got):
                    for c in g.children:
                        if c.i < i or c in got or c.dep_ in NOT_IDIOM_LINK:
                            continue
                        el = next((e for e in rest if self._fixed_at(view, c.i, e)), None)
                        if el is not None:
                            rest.remove(el)
                            got.append(c)
                            grew = True
            if not rest:
                return sorted(g.i for g in got)
        return None

    def _valid(self, view, pat, idx):
        """맞춘 결과를 품사·구문으로 검증한다."""
        doc = view.doc
        last = doc[idx[-1]]
        matched = set(idx)

        # be 숙어에 말이 끼면 그냥 서술이다 (was a sensible man은 be a man이 아니다)
        if doc[idx[0]].lemma_ == "be" and idx[-1] - idx[0] + 1 != len(idx):
            return False

        # to부정사의 to는 전치사가 아니다 (want to go, have to go)
        if len(idx) == 2 and last.tag_ == "TO":
            return False

        # 동사 뒤에 말이 낀 구동사: 불변화사가 뒤따르는 목적어를 가진 전치사면 숙어가 아니다
        # (put the book up the stairs). 숙어 안에 목적어가 있으면 괜찮다 (take it into account)
        if pat.pos == "verb":
            takes_object = last.dep_ == "prep" and any(
                c.dep_ in ("pobj", "pcomp") and c.i not in matched for c in last.children)
            split = idx[1] - idx[0] > 1
            if takes_object and (split or pat.intransitive_only):
                return False
            # 불변화사가 낀 말 안의 다른 동사에 붙어 있으면 숙어가 아니다
            # (got a contract to paint a tramp that had come round)
            if split and len(idx) == 2:
                up = last.head
                if up.i != idx[0] and not (idx[0] < up.i < idx[1] and up.head.i == idx[0]
                                           and up.pos_ in NOUN_LIKE):
                    return False

        # 감탄사는 문장 맨 앞에서만 받는다 (He looked the word up의 word up은 아니다)
        if pat.pos == "intj":
            first = doc[idx[0]]
            if first.i != first.sent.start and not doc[first.i - 1].is_punct:
                return False

        # 명사 숙어가 동사로 끝나면 품사가 다르게 쓰인 것이다
        if pat.pos == "noun" and last.pos_ in ("VERB", "AUX"):
            return False

        # 앞뒤 자리
        if pat.lead:
            before = idx[0] - 1
            if before < 0:
                return False
            t = doc[before]
            if pat.lead == "POSS" and not (t.tag_ in ("PRP$", "POS")):
                return False
            if pat.lead == "NP" and t.pos_ not in NOUN_LIKE:
                return False
        if pat.trail:
            after = idx[-1] + 1
            if after >= view.sent_end[idx[-1]]:
                return False
            t = doc[after]
            if pat.trail == "REFL" and view.lower[after] not in REFLEXIVES:
                return False
            if pat.trail == "POSS" and t.tag_ != "PRP$" and t.pos_ not in ("NOUN", "PROPN", "DET", "ADJ"):
                return False
            if pat.trail == "NP" and t.pos_ not in (*NOUN_LIKE, "DET", "ADJ"):
                return False
        return True

    def detect(self, doc):
        """Doc → 찾은 숙어 목록. 겹치면 고정 단어가 많은 쪽을 남긴다."""
        view = View(doc)
        keys = set(view.where)
        found = []
        seen = set()
        for anchor in keys & self.by_anchor.keys():
            for pat in self.by_anchor[anchor]:
                if pat.idiom_id in seen:
                    continue
                if not all(w in keys or (w in ARTICLES and keys & ARTICLES) for w in pat.fixed[1:]):
                    continue
                for idx in [*self._align(view, pat), self._catena(view, pat)]:
                    if idx and self._valid(view, pat, idx):
                        found.append((pat, idx))
                        seen.add(pat.idiom_id)
                        break

        # 겹침 정리. 대명사를 뺀 고정 단어가 많은 쪽, 같으면 동사 숙어, 그다음 구간이 짧은 쪽.
        # give it up(환호하다)은 gave it up의 it이 give up의 목적어일 때가 훨씬 많다
        def content(m):
            return [i for i in m[1] if doc[i].pos_ != "PRON"]

        found.sort(key=lambda m: (-len(content(m)), len(m[1]), m[0].pos != "verb",
                                  m[1][-1] - m[1][0], m[1][0]))
        kept, used = [], set()
        for pat, idx in found:
            if used & set(content((pat, idx))):
                continue
            used.update(content((pat, idx)))
            kept.append((pat, idx))
        kept.sort(key=lambda m: m[1][0])
        return [self._result(doc, pat, idx) for pat, idx in kept]

    @staticmethod
    def _result(doc, pat, idx):
        fixed = set(idx)
        span = doc[idx[0]:idx[-1] + 1]
        gap = [t.text for t in span if t.i not in fixed and not t.is_punct]
        return {
            "idiom": pat.phrase,
            "idiom_id": pat.idiom_id,
            "pos": pat.pos,
            "level": pat.level,
            "as_found": span.text,
            "tokens": [[doc[i].idx, doc[i].idx + len(doc[i].text)] for i in idx],
            "span": [span.start_char, span.end_char],
            "gap": " ".join(gap),
            "continuous": not gap,
        }

    def senses(self, idiom_id):
        conn = sqlite3.connect(self.senses_db)
        rows = conn.execute("SELECT gloss, tags, literal FROM idiom_senses WHERE idiom_id = ? ORDER BY sense_idx",
                            (idiom_id,)).fetchall()
        conn.close()
        return [{"gloss": g, "tags": json.loads(t), "literal": bool(lit)} for g, t, lit in rows]

    def find(self, text):
        """문장 → 찾은 숙어 + 뜻. API와 CLI가 쓴다."""
        results = self.detect(self.nlp(text))
        for r in results:
            r["senses"] = self.senses(r["idiom_id"])
        return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--text", required=True)
    parser.add_argument("--model", default="en_core_web_sm")
    args = parser.parse_args()
    detector = IdiomDetector(nlp=spacy.load(args.model))
    for r in detector.find(args.text):
        print(f"{r['idiom']}  ←  {r['as_found']}" + (f"  (낀 말: {r['gap']})" if r["gap"] else ""))
        for s in r["senses"][:3]:
            print(f"    {'(literal) ' if s['literal'] else ''}{s['gloss'][:90]}")
