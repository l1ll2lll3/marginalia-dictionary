#!/usr/bin/env python3
"""
build_dict_db.py — kaikki.org Wiktionary JSONL → SQLite 사전 DB 빌드

140만 항목을 SQLite에 넣어서 즉시 lookup 가능하게.

Usage:
    python build_dict_db.py              # 빌드 (~3분)
    python build_dict_db.py --stats      # 통계만
"""

import json
import sqlite3
import sys
import io
import time
import argparse
from pathlib import Path

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

        CREATE TABLE words (
            id INTEGER PRIMARY KEY,
            word TEXT NOT NULL,
            word_normalized TEXT NOT NULL,
            pos TEXT,
            ipa TEXT,
            etymology TEXT
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
    """)

    # --- Words from kaikki.org ---
    print(f"Scanning {KAIKKI.name}...")
    word_id = 0
    sense_id = 0
    scanned = 0
    batch_words = []
    batch_senses = []
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

            # IPA — prefer US, fallback to first
            ipa = None
            for sound in entry.get("sounds", []):
                if "ipa" in sound:
                    tags = sound.get("tags", [])
                    if "US" in tags:
                        ipa = sound["ipa"]
                        break
                    elif ipa is None:
                        ipa = sound["ipa"]

            etymology = entry.get("etymology_text", "")

            word_id += 1
            batch_words.append((
                word_id, word, normalize(word), pos, ipa, etymology or None
            ))

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
                c.executemany("INSERT INTO words VALUES (?,?,?,?,?,?)", batch_words)
                c.executemany("INSERT INTO senses VALUES (?,?,?,?,?)", batch_senses)
                batch_words.clear()
                batch_senses.clear()

    # Flush remaining
    if batch_words:
        c.executemany("INSERT INTO words VALUES (?,?,?,?,?,?)", batch_words)
        c.executemany("INSERT INTO senses VALUES (?,?,?,?,?)", batch_senses)

    conn.commit()
    print(f"  Words: {word_id:,}, Senses: {sense_id:,}")

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


def stats():
    conn = sqlite3.connect(str(DB_PATH))
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM words")
    print(f"Words: {c.fetchone()[0]:,}")
    c.execute("SELECT COUNT(*) FROM senses")
    print(f"Senses: {c.fetchone()[0]:,}")
    c.execute("SELECT COUNT(*) FROM idioms")
    print(f"Idioms: {c.fetchone()[0]:,}")
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
