#!/usr/bin/env python3
"""dict.db에 등급 표(word_levels)를 얹는다.

    python en-en/scripts/build_levels.py          # build_dict_db.py 다음에 실행 (수십 초)
    python en-en/scripts/build_levels.py --check went colour object

등급 체계 두 개 (docs/grading_sources.md §5):

  cefr                 CEFR-J 1.5 (A1~B2) + Octanove 1.0 (C1~C2). 단어 + 품사 단위
  kr_curriculum_2022   2022 개정 교육과정 기본 어휘. 품사 구분이 없어 pos='*'
                       elementary(초등) / middle_common(중고 공통) / high_elective(고교 선택)

원칙:
  - 목록에 실제로 있는 것만 넣는다. 행이 없으면 "목록에 없음"이다. 빈도로 추정하지 않는다.
  - 굴절형·철자 이형은 원형의 등급을 물려받는다 (went → go, colour → color).
    source='inherited', inherited_from=원형. 단 아래 경우는 물려받지 않는다:
      · 그 (단어, 품사)의 첫 항목이 원형을 가리키지 않을 때 — found(설립하다)가
        find의 과거형이라는 이유로 A1이 되면 안 된다
      · 첫 뜻에 굴절·표준 이형이 아닌 태그가 있을 때 (고어·방언·약어·오용 등)
        — shew(고어 show)는 A1이 아니다. 허용 목록은 INHERIT_OK_TAGS
  - 같은 칸에 값이 여럿이면 낮은 등급을 남긴다 (학습자가 처음 만나는 수준).
"""

import argparse
import csv
import sqlite3
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
EN_EN = HERE.parent
DB_PATH = EN_EN / "data" / "build" / "dict.db"
KR_CSV = EN_EN / "data" / "kr_curriculum" / "moe_2022_basic_vocab.csv"

sys.path.insert(0, str(HERE))
from build_dict_db import normalize                      # noqa: E402
from cefr_grading import load_reference, CEFR_ORDER      # noqa: E402

KR_ORDER = {"elementary": 0, "middle_common": 1, "high_elective": 2}

# CEFR 목록 품사 → kaikki 품사
LIST_TO_KAIKKI = {
    "noun": ["noun"],
    "verb": ["verb"],
    "modal auxiliary": ["verb"],
    "be-verb": ["verb"],
    "do-verb": ["verb"],
    "have-verb": ["verb"],
    "adjective": ["adj"],
    "adverb": ["adv"],
    "pronoun": ["pron"],
    "preposition": ["prep"],
    "determiner": ["det", "article"],
    "conjunction": ["conj"],
    "number": ["num"],
    "interjection": ["intj"],
    "infinitive-to": ["particle"],
}

# 첫 뜻의 태그가 전부 이 안에 있을 때만 등급을 물려준다 (허용 목록).
#
# 막을 태그를 나열하는 방식으로 시작했다가 Cornwall·Geordie·Internet·misconstruction
# (temperment ← temperament) 같은 것이 계속 새어 들어왔다. 지역 방언 태그는 끝이 없어서
# 거꾸로 "굴절형·표준 이형임을 뜻하는 태그"만 허용한다. agent(runner ← run 같은 파생)도
# 굴절이 아니므로 뺀다.
INHERIT_OK_TAGS = {
    # 굴절
    "form-of", "plural", "plural-of", "singular", "participle", "past", "present",
    "gerund", "indicative", "third-person", "simple", "comparative", "superlative",
    # 표준 철자 이형
    "alt-of", "alternative", "standard", "uk", "us", "british", "american",
    "commonwealth", "canada", "ireland", "australia", "new-zealand",
    # 뜻과 무관한 문법 표시
    "countable", "uncountable", "not-comparable", "usually", "transitive", "intransitive",
}


def create_table(c):
    c.executescript("""
        DROP TABLE IF EXISTS word_levels;
        CREATE TABLE word_levels (
            word_normalized TEXT NOT NULL,
            pos             TEXT NOT NULL,   -- kaikki 품사, 품사 구분 없는 체계는 '*'
            scheme          TEXT NOT NULL,   -- cefr | kr_curriculum_2022
            level           TEXT NOT NULL,
            source          TEXT NOT NULL,   -- cefr-j | octanove | moe-2022 | inherited
            inherited_from  TEXT,            -- inherited: 원형 / moe-2022: 단어군 대표형(이형·파생형일 때)
            PRIMARY KEY (word_normalized, pos, scheme)
        );
        CREATE INDEX idx_levels_word ON word_levels(word_normalized);
    """)


def keep_lower(table, key, value, order):
    prev = table.get(key)
    if prev is None or order[value[0]] < order[prev[0]]:
        table[key] = value


def link_candidates(c):
    """(단어, 품사)마다 첫 항목이 원형을 가리키면 그 원형을 돌려준다.

    결과: {(word_normalized, pos): target_normalized}
    """
    rows = c.execute("""
        SELECT w.word_normalized, w.pos, l.target, l.tags
        FROM words w
        JOIN (SELECT word_normalized, pos, MIN(id) AS first_id
              FROM words GROUP BY word_normalized, pos) f ON f.first_id = w.id
        JOIN word_links l ON l.word_id = w.id
        ORDER BY w.id, l.rowid
    """).fetchall()
    links, skipped = {}, Counter()
    for word, pos, target, tags in rows:
        if (word, pos) in links:
            continue
        tag_set = {t.lower() for t in (tags or "").split()}
        blocked = tag_set - INHERIT_OK_TAGS
        if blocked:
            skipped[sorted(blocked)[0]] += 1
            continue
        target = normalize(target)
        if target != word:
            links[(word, pos)] = target
    return links, skipped


def cefr_levels(c, links):
    existing = set(c.execute("SELECT DISTINCT word_normalized, pos FROM words").fetchall())
    direct, missing = {}, Counter()
    for (headword, list_pos), (cefr, source) in load_reference().items():
        for pos in LIST_TO_KAIKKI.get(list_pos, []):
            key = (normalize(headword), pos)
            if key in existing:
                keep_lower(direct, key, (cefr, source, None), CEFR_ORDER)
            else:
                missing[list_pos] += 1

    inherited = {}
    for (word, pos), target in links.items():
        if (word, pos) in direct:
            continue
        hit = direct.get((target, pos))
        if hit:
            inherited[(word, pos)] = (hit[0], "inherited", target)
    return direct, inherited, missing


def kr_levels(links):
    direct = {}
    with open(KR_CSV, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            family = None if row["kind"] == "headword" else normalize(row["family"])
            keep_lower(direct, (normalize(row["word"]), "*"),
                       (row["level"], "moe-2022", family), KR_ORDER)

    inherited = {}
    for (word, _pos), target in links.items():
        if (word, "*") in direct:
            continue
        hit = direct.get((target, "*"))
        if hit:
            keep_lower(inherited, (word, "*"), (hit[0], "inherited", target), KR_ORDER)
    return direct, inherited


def build():
    if not KR_CSV.exists():
        sys.exit(f"교육과정 CSV가 없다: {KR_CSV}\n  python en-en/scripts/parse_kr_curriculum.py")
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    create_table(c)

    links, skipped = link_candidates(c)
    print(f"원형 연결 {len(links):,}개 (첫 항목 기준) · 상속 제외 사유(태그) 상위 {skipped.most_common(5)}")

    cefr_direct, cefr_inherited, cefr_missing = cefr_levels(c, links)
    kr_direct, kr_inherited = kr_levels(links)

    rows = []
    for scheme, table in (("cefr", cefr_direct), ("cefr", cefr_inherited),
                          ("kr_curriculum_2022", kr_direct), ("kr_curriculum_2022", kr_inherited)):
        for (word, pos), (level, source, origin) in table.items():
            rows.append((word, pos, scheme, level, source, origin))
    c.executemany("INSERT INTO word_levels VALUES (?,?,?,?,?,?)", rows)
    conn.commit()

    print(f"\ncefr               목록 {len(cefr_direct):,} + 상속 {len(cefr_inherited):,}")
    if cefr_missing:
        print(f"  사전에 같은 (단어, 품사)가 없어 못 넣은 목록 항목: {sum(cefr_missing.values()):,} "
              f"{dict(cefr_missing.most_common(4))}")
    print(f"kr_curriculum_2022 목록 {len(kr_direct):,} + 상속 {len(kr_inherited):,}")
    for scheme, in c.execute("SELECT DISTINCT scheme FROM word_levels ORDER BY 1").fetchall():
        dist = c.execute("SELECT level, COUNT(*) FROM word_levels WHERE scheme=? "
                         "GROUP BY level ORDER BY level", (scheme,)).fetchall()
        print(f"  {scheme}: {dict(dist)}")
    conn.close()


def check(words):
    conn = sqlite3.connect(DB_PATH)
    for word in words:
        rows = conn.execute("SELECT pos, scheme, level, source, inherited_from FROM word_levels "
                            "WHERE word_normalized=? ORDER BY scheme, pos", (normalize(word),)).fetchall()
        print(f"{word}:")
        for pos, scheme, level, source, origin in rows or [("—", "—", "목록에 없음", "", None)]:
            print(f"  {scheme:<20} {pos:<6} {level:<14} {source}{f' ← {origin}' if origin else ''}")
    conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", nargs="+", metavar="WORD", help="이 단어들의 등급만 보여준다")
    args = parser.parse_args()
    check(args.check) if args.check else build()
