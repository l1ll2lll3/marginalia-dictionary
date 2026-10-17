#!/usr/bin/env python3
"""CEFR-J + Octanove 기반 어휘 등급 판정.

기존 등급은 CEFR이 아니라 `wordfreq`의 zipf 빈도를 CEFR 라벨로 갈아끼운 것이었다
(build_great_gatsby.py의 CEFR_THRESHOLDS). 그래서 soldier·politician 같은
중간 빈도 단어가 전부 B2에 몰렸다.

여기서는 실제 CEFR 참조 목록을 쓴다. 둘 다 품사별로 등급이 매겨져 있어
heteronym(object 명사/동사)도 구분할 수 있다.

  CEFR-J Wordlist 1.5    A1–B2, 7,798행. Yukio Tono, Tokyo Univ. of Foreign Studies.
                         연구·상업 이용 무료 (출처 표기 조건)
  Octanove Profile 1.0   C1–C2, 2,136행. Octanove Labs. CC BY-SA 4.0

**미수록 단어 처리** — 두 목록을 합쳐도 9,984쌍뿐이라 문학 어휘의 36%가 빠진다
(discern, pompous, capricious…). CEFR-J가 A1–B2를 망라하므로 "목록에 없다"는
구조상 "B2 초과"를 뜻한다. 그 안에서만 빈도로 C1/C2를 가르고, 어느 근거로
매겼는지 `cefr_source`에 남겨 나중에 감사할 수 있게 한다.
"""

import csv
import re
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "cefr"
CEFRJ_CSV = DATA_DIR / "cefrj-vocabulary-profile-1.5.csv"
OCTANOVE_CSV = DATA_DIR / "octanove-vocabulary-profile-c1c2-1.0.csv"

CEFR_ORDER = {"A1": 0, "A2": 1, "B1": 2, "B2": 3, "C1": 4, "C2": 5}

# spaCy 품사 → 목록의 품사 표기
POS_TO_LIST = {
    "NOUN": "noun",
    "PROPN": "noun",
    "VERB": "verb",
    "AUX": "verb",
    "ADJ": "adjective",
    "ADV": "adverb",
}

# 목록 밖 단어를 C1과 C2로 가르는 경계. C 구간 안에서만 쓰는 보조 신호다.
C_BAND_ZIPF = 3.0

SOURCE_CEFRJ = "cefr-j"
SOURCE_OCTANOVE = "octanove"
SOURCE_FREQUENCY = "frequency"
SOURCE_PROPER = "proper-noun"

# 고유명사·고유형용사에 매기는 등급.
# CEFR-J·Octanove는 고유명사를 싣지 않는다. 빈도로 매기면 Strickland가 C1,
# English가 C1이 되어 어휘 학습 자료에 인물명이 올라간다. 등급의 목적이
# "이 단어를 학습 자료에 실을 것인가"이므로 낮은 등급을 줘서 걸러지게 한다.
PROPER_NOUN_LEVEL = "A2"


def _normalize_pos(raw):
    pos = (raw or "").strip().lower()
    return "verb" if pos == "vern" else pos      # Octanove에 오타 1건


def load_reference():
    """(headword, pos) → (CEFR, 출처). 같은 쌍이 겹치면 낮은 등급을 남긴다.

    학습자가 먼저 만나는 수준이 그 단어의 문턱이기 때문이다.
    """
    table = {}

    def ingest(path, source):
        if not path.exists():
            raise SystemExit(f"참조 목록이 없다: {path}\n  cefr_data/ 를 확인할 것")
        with open(path, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                cefr = (row.get("CEFR") or "").strip().upper()
                if cefr not in CEFR_ORDER:
                    continue
                pos = _normalize_pos(row.get("pos"))
                # "adviser/advisor"처럼 이형을 슬래시로 묶어둔 항목이 167개 있다
                for headword in (row.get("headword") or "").split("/"):
                    headword = headword.strip().lower()
                    if not headword:
                        continue
                    key = (headword, pos)
                    prev = table.get(key)
                    if prev is None or CEFR_ORDER[cefr] < CEFR_ORDER[prev[0]]:
                        table[key] = (cefr, source)

    ingest(CEFRJ_CSV, SOURCE_CEFRJ)
    ingest(OCTANOVE_CSV, SOURCE_OCTANOVE)
    return table


class Grader:
    def __init__(self):
        self.table = load_reference()
        self._heads = {h for h, _ in self.table}
        self._zipf = None

    def _frequency(self, word):
        if self._zipf is None:
            from wordfreq import zipf_frequency
            self._zipf = zipf_frequency
        return self._zipf(word.lower(), "en")

    def grade(self, lemma, pos):
        """(등급, 출처, 품사일치여부)를 돌려준다.

        품사일치여부는 목록에서 찾았을 때만 의미가 있다. 목록에 아예 없어
        빈도로 매긴 경우에는 None — False로 두면 "품사가 어긋났다"는 오해를 준다.
        """
        word = (lemma or "").lower()
        want = POS_TO_LIST.get(pos)

        hit = self.table.get((word, want)) if want else None
        if hit:
            return hit[0], hit[1], True

        # 품사는 다르지만 같은 철자가 목록에 있는 경우 — 가장 낮은 등급을 쓴다
        alternatives = [
            value for (head, _), value in self.table.items() if head == word
        ]
        if alternatives:
            cefr, source = min(alternatives, key=lambda v: CEFR_ORDER[v[0]])
            return cefr, source, False

        # 목록 밖 = B2 초과. C 구간 안에서만 빈도로 가른다.
        z = self._frequency(word)
        return ("C1" if z >= C_BAND_ZIPF else "C2"), SOURCE_FREQUENCY, None

    def covers(self, lemma):
        return (lemma or "").lower() in self._heads


def looks_proper(forms_in_book):
    """본문 출현형이 모두 대문자로 시작하면 고유명사·고유형용사로 본다.

    Strickland, Stroeve 같은 인물명과 English, French 같은 국적 형용사가 여기 걸린다.
    """
    forms = [f for f in (forms_in_book or []) if f]
    return bool(forms) and all(f[:1].isupper() for f in forms)


def is_clean_lemma(lemma):
    """표제어로 쓸 수 있는 형태인지. 각주 기호나 문장 파편이 섞인 것을 거른다.

    실제로 'book[1', 'why?—alarm', 'married”—captain' 같은 값이 들어 있었다.
    """
    return bool(re.fullmatch(r"[A-Za-z][A-Za-z'\-]*", lemma or ""))
