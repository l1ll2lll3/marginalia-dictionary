#!/usr/bin/env python3
"""
build_dict_db.py — kaikki.org Wiktionary JSONL → SQLite 사전 DB 빌드

140만 항목을 SQLite에 넣어서 즉시 lookup 가능하게.

발음은 extract_pronunciations._pick_ipa()로 고른다 (US 우선 + 축약형·근거 없는
파찰음·방언·영국식 기호 감점). 예전의 "US 태그, 없으면 첫 번째"는 object 동사에
명사 발음을 붙이는 등 틀린 경우가 많았다.

만드는 표: words, senses, idioms, word_links, pronunciations.
등급(word_levels)은 이 DB 위에 build_levels.py가 따로 얹는다.

Usage:
    python build_dict_db.py              # 빌드 (~5분)
    python build_dict_db.py --stats      # 통계만
"""

import json
import sqlite3
import sys
import io
import time
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from extract_pronunciations import _pick_ipa, _variant_target  # noqa: E402

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

KAIKKI = Path(__file__).resolve().parent.parent / "data" / "raw" / "kaikki-en.jsonl"
IDIOMS = Path(__file__).resolve().parent.parent / "data" / "raw" / "english_idioms.json"
DB_PATH = Path(__file__).resolve().parent.parent / "data" / "build" / "dict.db"

ARCHAIC_NORM = {
    "\u00e6": "ae", "\u0153": "oe", "\u00eb": "e", "\u00e9": "e",
    "\u00e8": "e", "\u00e0": "a", "\u00e2": "a", "\u00ee": "i",
    "\u00f4": "o", "\u00fb": "u",
}


def normalize(word: str) -> str:
    result = word.lower()
    for old, new in ARCHAIC_NORM.items():
        result = result.replace(old, new)
    return result


def build():
    t0 = time.time()
    conn = sqlite3.connect(str(DB_PATH))
    c = conn.cursor()

    c.executescript("""
        DROP TABLE IF EXISTS words;
        DROP TABLE IF EXISTS senses;
        DROP TABLE IF EXISTS idioms;
        DROP TABLE IF EXISTS word_links;
        DROP TABLE IF EXISTS pronunciations;

        CREATE TABLE words (
            id INTEGER PRIMARY KEY,
            word TEXT NOT NULL,
            word_normalized TEXT NOT NULL,
            pos TEXT,
            ipa TEXT,
            ipa_variety TEXT,
            etymology TEXT
        );

        -- 이 항목이 다른 단어를 가리키는 연결 (went → go, colour → color).
        -- 등급 상속(build_levels.py)과 철자 변형 발음에 쓴다.
        CREATE TABLE word_links (
            word_id INTEGER NOT NULL REFERENCES words(id),
            target  TEXT NOT NULL,
            kind    TEXT NOT NULL,   -- form_of | alt_of | spelling
            tags    TEXT             -- 첫 뜻의 태그, 공백 구분 (past, archaic …)
        );

        CREATE TABLE senses (
            id INTEGER PRIMARY KEY,
            word_id INTEGER NOT NULL,
            sense_num INTEGER NOT NULL,
            gloss TEXT NOT NULL,
            example TEXT,
            FOREIGN KEY (word_id) REFERENCES words(id)
        );

        CREATE TABLE idioms (
            id INTEGER PRIMARY KEY,
            phrase TEXT NOT NULL,
            phrase_normalized TEXT NOT NULL,
            meaning TEXT
        );

        CREATE INDEX idx_words_normalized ON words(word_normalized);
        CREATE INDEX idx_words_word ON words(word);
        CREATE INDEX idx_senses_word_id ON senses(word_id);
        CREATE INDEX idx_idioms_normalized ON idioms(phrase_normalized);
        CREATE INDEX idx_links_word ON word_links(word_id);
    """)

    # --- Words from kaikki.org ---
    print(f"Scanning {KAIKKI.name}...")
    word_id = 0
    sense_id = 0
    scanned = 0
    batch_words = []
    batch_senses = []
    batch_links = []
    BATCH_SIZE = 10000

    with open(KAIKKI, "r", encoding="utf-8") as f:
        for line in f:
            scanned += 1
            if scanned % 200_000 == 0:
                elapsed = time.time() - t0
                print(f"  {scanned:>10,} scanned, {word_id:,} words ({elapsed:.0f}s)")

            entry = json.loads(line)
            word = entry.get("word", "")
            if not word:
                continue

            pos = entry.get("pos", "")
            senses_raw = entry.get("senses", [])
            if not senses_raw:
                continue

            ipa, variety = _pick_ipa(entry.get("sounds"), word)

            etymology = entry.get("etymology_text", "")

            word_id += 1
            batch_words.append((
                word_id, word, normalize(word), pos, ipa, variety, etymology or None
            ))

            # 첫 뜻이 굴절형·이형이면 그 원형을 기록한다 (went → go)
            first = senses_raw[0]
            first_tags = " ".join(first.get("tags") or []) or None
            for kind in ("form_of", "alt_of"):
                for ref in first.get(kind) or []:
                    target = (ref.get("word") or "").strip()
                    if target:
                        batch_links.append((word_id, target, kind, first_tags))
                        break
            spelling = _variant_target(entry)
            if spelling and spelling.lower() != word.lower():
                batch_links.append((word_id, spelling, "spelling", first_tags))

            # Senses
            for si, sense in enumerate(senses_raw):
                glosses = sense.get("glosses", [])
                if not glosses:
                    continue
                gloss = glosses[-1] if len(glosses) > 1 else glosses[0]

                example = None
                for ex in sense.get("examples", []):
                    text = ex.get("text", "").strip()
                    if text and len(text) < 300:
                        example = text
                        if ex.get("type") == "example":
                            break

                sense_id += 1
                batch_senses.append((
                    sense_id, word_id, si + 1, gloss, example
                ))

            if len(batch_words) >= BATCH_SIZE:
                c.executemany("INSERT INTO words VALUES (?,?,?,?,?,?,?)", batch_words)
                c.executemany("INSERT INTO senses VALUES (?,?,?,?,?)", batch_senses)
                c.executemany("INSERT INTO word_links VALUES (?,?,?,?)", batch_links)
                batch_words.clear()
                batch_senses.clear()
                batch_links.clear()

    # Flush remaining
    if batch_words:
        c.executemany("INSERT INTO words VALUES (?,?,?,?,?,?,?)", batch_words)
        c.executemany("INSERT INTO senses VALUES (?,?,?,?,?)", batch_senses)
        c.executemany("INSERT INTO word_links VALUES (?,?,?,?)", batch_links)

    conn.commit()
    print(f"  Words: {word_id:,}, Senses: {sense_id:,}")

    build_pronunciations(c)
    conn.commit()

    # --- Idioms ---
    print(f"Loading {IDIOMS.name}...")
    with open(IDIOMS, "r", encoding="utf-8") as f:
        idioms = json.load(f)

    batch_idioms = []
    for i, entry in enumerate(idioms):
        phrase = entry.get("word", "")
        senses = entry.get("senses", [])
        meaning = senses[0] if senses else ""
        batch_idioms.append((i + 1, phrase, normalize(phrase), meaning))

    c.executemany("INSERT INTO idioms VALUES (?,?,?,?)", batch_idioms)
    conn.commit()
    print(f"  Idioms: {len(batch_idioms):,}")

    conn.close()

    elapsed = time.time() - t0
    size_mb = DB_PATH.stat().st_size / (1024 * 1024)
    print(f"\nDone: {DB_PATH.name} ({size_mb:.0f} MB) in {elapsed:.0f}s")


def build_pronunciations(c):
    """(단어, 품사)별 대표 발음 표.

    한 (단어, 품사)에 어원 항목이 여럿이면 Wiktionary 순서상 첫 항목(주된 뜻)의
    발음을 쓴다. 같은 정규형에 대소문자만 다른 항목(Polish/polish)이 있으면
    소문자 쪽을 먼저 본다.

    발음이 없는 철자 변형(colour)은 원형(color)의 발음을 가져오고 variant_of에
    적는다. 같은 품사를 먼저 찾고, 없으면 원형의 대표 발음을 쓴다.
    """
    print("Building pronunciations...")
    c.executescript("""
        CREATE TABLE pronunciations (
            word_normalized TEXT NOT NULL,
            pos             TEXT NOT NULL,
            ipa             TEXT NOT NULL,
            variety         TEXT,
            variant_of      TEXT,
            PRIMARY KEY (word_normalized, pos)
        );

        INSERT INTO pronunciations (word_normalized, pos, ipa, variety)
        SELECT word_normalized, pos, ipa, ipa_variety FROM (
            SELECT word_normalized, pos, ipa, ipa_variety,
                   ROW_NUMBER() OVER (
                       PARTITION BY word_normalized, pos
                       ORDER BY (word = word_normalized) DESC, id
                   ) AS rn
            FROM words WHERE ipa IS NOT NULL
        ) WHERE rn = 1;
    """)
    direct = c.execute("SELECT COUNT(*) FROM pronunciations").fetchone()[0]

    missing = c.execute("""
        SELECT w.word_normalized, w.pos, MIN(l.target)
        FROM words w JOIN word_links l ON l.word_id = w.id AND l.kind = 'spelling'
        WHERE NOT EXISTS (SELECT 1 FROM pronunciations p
                          WHERE p.word_normalized = w.word_normalized AND p.pos = w.pos)
        GROUP BY w.word_normalized, w.pos
    """).fetchall()

    resolved = []
    for word, pos, target in missing:
        t = normalize(target)
        row = c.execute("SELECT ipa, variety FROM pronunciations WHERE word_normalized=? AND pos=?",
                        (t, pos)).fetchone()
        if row is None:
            row = c.execute("SELECT ipa, variety FROM pronunciations WHERE word_normalized=? "
                            "ORDER BY rowid LIMIT 1", (t,)).fetchone()
        if row:
            resolved.append((word, pos, row[0], row[1], target))
    c.executemany("INSERT OR IGNORE INTO pronunciations VALUES (?,?,?,?,?)", resolved)
    print(f"  Pronunciations: {direct:,} direct + {len(resolved):,} from spelling variants")


def stats():
    conn = sqlite3.connect(str(DB_PATH))
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM words")
    print(f"Words: {c.fetchone()[0]:,}")
    c.execute("SELECT COUNT(*) FROM senses")
    print(f"Senses: {c.fetchone()[0]:,}")
    c.execute("SELECT COUNT(*) FROM idioms")
    print(f"Idioms: {c.fetchone()[0]:,}")
    for table in ("word_links", "pronunciations", "word_levels"):
        try:
            n = c.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            print(f"{table}: {n:,}")
        except sqlite3.OperationalError:
            print(f"{table}: (없음)")
    size_mb = DB_PATH.stat().st_size / (1024 * 1024)
    print(f"Size: {size_mb:.0f} MB")
    conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--stats", action="store_true")
    args = parser.parse_args()
    if args.stats:
        stats()
    else:
        build()
