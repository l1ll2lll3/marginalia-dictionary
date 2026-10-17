#!/usr/bin/env python3
"""
dict.py — 로컬 영어 사전 (Wiktionary + 숙어)

Usage:
    python dict.py bourdon
    python dict.py mediævalism
    python dict.py "take care of"
    python dict.py draw --max 10        # 뜻 최대 10개
    python dict.py --search "medi*"     # 와일드카드 검색
"""

import sqlite3
import sys
import io
import re
import argparse
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

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


def lookup_word(conn, query, max_senses=0):
    c = conn.cursor()
    norm = normalize(query)
    original_has_archaic = norm != query.lower()

    # Exact match on normalized form
    c.execute("""
        SELECT id, word, pos, ipa, etymology
        FROM words WHERE word_normalized = ?
        ORDER BY id
    """, (norm,))
    rows = c.fetchall()

    if not rows:
        # Try LIKE for partial match
        c.execute("""
            SELECT id, word, pos, ipa, etymology
            FROM words WHERE word_normalized LIKE ?
            ORDER BY id LIMIT 20
        """, (norm + "%",))
        rows = c.fetchall()
        if rows:
            print(f"  No exact match for '{query}'. Did you mean:")
            seen = set()
            for _, word, pos, _, _ in rows:
                key = f"{word} ({pos})"
                if key not in seen:
                    seen.add(key)
                    print(f"    {word} [{pos}]")
            return
        else:
            print(f"  '{query}' not found.")
            return

    # Group by (word, pos) to avoid duplicate entries
    for word_id, word, pos, ipa, etymology in rows:
        # Header
        header = f"  {word}"
        if original_has_archaic and word.lower() != query.lower():
            header = f"  {query} → {word}"
        if pos:
            header += f"  [{pos}]"
        if ipa:
            header += f"  {ipa}"
        print(header)

        # Senses
        c.execute("""
            SELECT sense_num, gloss, example
            FROM senses WHERE word_id = ?
            ORDER BY sense_num
        """, (word_id,))
        senses = c.fetchall()

        limit = max_senses if max_senses > 0 else len(senses)
        for num, gloss, example in senses[:limit]:
            print(f"    {num}. {gloss}")
            if example:
                print(f"       ex: {example[:120]}")
        if max_senses > 0 and len(senses) > max_senses:
            print(f"    ... +{len(senses) - max_senses} more (use --max 0 for all)")

        # Etymology
        if etymology:
            print(f"    Etymology: {etymology[:200]}")

        print()


def lookup_idiom(conn, query):
    c = conn.cursor()
    norm = normalize(query)

    c.execute("""
        SELECT phrase, meaning FROM idioms
        WHERE phrase_normalized = ?
    """, (norm,))
    rows = c.fetchall()

    if not rows:
        # Try stripping leading article (a/an/the)
        stripped = re.sub(r"^(a|an|the)\s+", "", norm)
        if stripped != norm:
            c.execute("""
                SELECT phrase, meaning FROM idioms
                WHERE phrase_normalized = ?
            """, (stripped,))
            rows = c.fetchall()

    if not rows:
        c.execute("""
            SELECT phrase, meaning FROM idioms
            WHERE phrase_normalized LIKE ?
            LIMIT 10
        """, ("%" + norm + "%",))
        rows = c.fetchall()

    if rows:
        for phrase, meaning in rows:
            print(f"  {phrase}  [idiom]")
            if meaning:
                print(f"    {meaning}")
            print()
        return True
    return False


def search_words(conn, pattern):
    c = conn.cursor()
    sql_pattern = normalize(pattern).replace("*", "%").replace("?", "_")

    c.execute("""
        SELECT DISTINCT word, pos FROM words
        WHERE word_normalized LIKE ?
        ORDER BY word LIMIT 30
    """, (sql_pattern,))

    results = c.fetchall()
    if results:
        print(f"  Matches for '{pattern}':")
        for word, pos in results:
            print(f"    {word} [{pos}]")
    else:
        print(f"  No matches for '{pattern}'.")


def main():
    parser = argparse.ArgumentParser(description="Local English Dictionary (Wiktionary)")
    parser.add_argument("word", nargs="*", help="Word or idiom to look up")
    parser.add_argument("--max", type=int, default=10, help="Max senses to show (0=all)")
    parser.add_argument("--search", help="Wildcard search (e.g. 'medi*')")
    args = parser.parse_args()

    if not DB_PATH.exists():
        print(f"ERROR: {DB_PATH} not found. Run: python build_dict_db.py")
        return

    conn = sqlite3.connect(str(DB_PATH))

    if args.search:
        search_words(conn, args.search)
    elif args.word:
        query = " ".join(args.word)
        print()
        # Try idiom first if multi-word
        if " " in query:
            found = lookup_idiom(conn, query)
            if not found:
                print(f"  '{query}' not found as idiom. Trying as word...")
                lookup_word(conn, query, args.max)
        else:
            lookup_word(conn, query, args.max)
            # Also check idioms containing this word
            c = conn.cursor()
            c.execute("""
                SELECT phrase, meaning FROM idioms
                WHERE phrase_normalized LIKE ?
                LIMIT 5
            """, ("%" + normalize(query) + "%",))
            idiom_rows = c.fetchall()
            if idiom_rows:
                print(f"  Related idioms:")
                for phrase, meaning in idiom_rows:
                    m = f" — {meaning[:60]}" if meaning else ""
                    print(f"    {phrase}{m}")
                print()
    else:
        parser.print_help()

    conn.close()


if __name__ == "__main__":
    main()
