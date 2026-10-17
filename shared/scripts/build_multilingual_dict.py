"""
Build Multilingual Dictionary from Wiktionary Data

Sources:
  1. kaikki.org-dictionary-English.jsonl (1.4M entries) → EN→KO, EN→ZH direct translations
  2. raw-wiktextract-data.jsonl (10.2M entries) → KO→EN, ZH→EN entries → reverse to EN→KO, EN→ZH

Output:
  multilingual_dict.json — combined dictionary for all 6 language pairs:
    EN→KO, EN→ZH, KO→EN, KO→ZH, ZH→EN, ZH→KO

Usage:
  python build_multilingual_dict.py                  # Full build (slow, ~20min)
  python build_multilingual_dict.py --stats          # Show stats only
  python build_multilingual_dict.py --lookup word    # Test lookup
"""

import gzip
import json
import sys
import time
import re
from pathlib import Path
from collections import defaultdict

sys.stdout.reconfigure(encoding='utf-8')

ROOT = Path(__file__).resolve().parent.parent.parent
WIKT_DIR = ROOT / "shared" / "data" / "raw"   # raw-wiktextract-data.jsonl 을 여기 둔다 (이 Mac에 없음)
EN_JSONL = ROOT / "en-en" / "data" / "raw" / "kaikki-en.jsonl"
RAW_JSONL = WIKT_DIR / "raw-wiktextract-data.jsonl"
RAW_JSONL_GZ = WIKT_DIR / "raw-wiktextract-data.jsonl.gz"   # fetch_data.py가 받는 형태
OUTPUT = ROOT / "shared" / "data" / "multilingual_dict.json"


def extract_en_translations():
    """Extract EN→KO and EN→ZH from English.jsonl translations field."""
    print("=" * 60)
    print("[1/4] Scanning English.jsonl for EN→KO/ZH translations...")
    print("=" * 60)

    en_ko = defaultdict(list)  # en_word -> [{word, pos, sense}]
    en_zh = defaultdict(list)
    count = 0

    with open(EN_JSONL, "r", encoding="utf-8") as f:
        for line in f:
            count += 1
            if count % 300000 == 0:
                print(f"  ...{count:,} entries", flush=True)
            entry = json.loads(line)
            if "translations" not in entry:
                continue
            word = entry["word"].lower().strip()
            pos = entry.get("pos", "")
            for t in entry["translations"]:
                code = t.get("code", "")
                tw = t.get("word", "").strip()
                if not tw:
                    continue
                sense = t.get("sense", "")
                item = {"word": tw, "sense": sense}
                if code == "ko":
                    en_ko[word].append(item)
                elif code in ("cmn", "zh"):
                    # Filter out romanization (Cyrillic, Latin)
                    if re.search(r'[\u4e00-\u9fff\u3400-\u4dbf]', tw):
                        en_zh[word].append(item)

    print(f"  EN→KO: {len(en_ko):,} words")
    print(f"  EN→ZH: {len(en_zh):,} words")
    return dict(en_ko), dict(en_zh)


def extract_ko_zh_entries():
    """Extract KO→EN and ZH→EN from raw-wiktextract-data.jsonl."""
    print()
    print("=" * 60)
    print("[2/4] Scanning raw-wiktextract-data.jsonl for KO/ZH entries...")
    print("      (20GB, this takes a few minutes)")
    print("=" * 60)

    ko_en = defaultdict(list)  # ko_word -> [{gloss, pos, examples}]
    zh_en = defaultdict(list)
    # Also collect KO/ZH translations from entries in these languages
    ko_zh_trans = defaultdict(list)  # ko_word -> [zh translations]
    zh_ko_trans = defaultdict(list)  # zh_word -> [ko translations]
    count = 0

    raw = open(RAW_JSONL, "r", encoding="utf-8") if RAW_JSONL.exists() \
        else gzip.open(RAW_JSONL_GZ, "rt", encoding="utf-8")
    with raw as f:
        for line in f:
            count += 1
            if count % 2000000 == 0:
                print(f"  ...{count:,} entries", flush=True)
            entry = json.loads(line)
            lang_code = entry.get("lang_code", "")
            word = entry.get("word", "").strip()
            pos = entry.get("pos", "")

            if not word:
                continue

            if lang_code == "ko":
                senses = entry.get("senses", [])
                for s in senses[:3]:
                    glosses = s.get("glosses", [])
                    if glosses:
                        gloss = glosses[-1]  # Last gloss is usually most specific
                        examples = [e.get("text", "") for e in s.get("examples", [])[:1]]
                        ko_en[word].append({
                            "gloss": gloss,
                            "pos": pos,
                            "examples": examples,
                        })
                # Check for ZH translations in KO entry
                for t in entry.get("translations", []):
                    if t.get("code") in ("cmn", "zh") and t.get("word"):
                        tw = t["word"].strip()
                        if re.search(r'[\u4e00-\u9fff]', tw):
                            ko_zh_trans[word].append(tw)

            elif lang_code == "zh":
                senses = entry.get("senses", [])
                for s in senses[:3]:
                    glosses = s.get("glosses", [])
                    if glosses:
                        gloss = glosses[-1]
                        examples = [e.get("text", "") for e in s.get("examples", [])[:1]]
                        zh_en[word].append({
                            "gloss": gloss,
                            "pos": pos,
                            "examples": examples,
                        })
                # Check for KO translations in ZH entry
                for t in entry.get("translations", []):
                    if t.get("code") == "ko" and t.get("word"):
                        zh_ko_trans[word].append(t["word"].strip())

    print(f"  KO→EN: {len(ko_en):,} words")
    print(f"  ZH→EN: {len(zh_en):,} words")
    print(f"  KO→ZH (direct): {len(ko_zh_trans):,} words")
    print(f"  ZH→KO (direct): {len(zh_ko_trans):,} words")
    return dict(ko_en), dict(zh_en), dict(ko_zh_trans), dict(zh_ko_trans)


def build_reverse_index(source_dict):
    """Reverse a dict: {foreign_word: [{gloss: en_word, ...}]} → {en_word: [foreign_words]}"""
    reverse = defaultdict(set)
    for foreign_word, entries in source_dict.items():
        for entry in entries:
            gloss = entry.get("gloss", "")
            # Extract English words from gloss (simple: take first word/phrase before parentheses)
            # Glosses look like: "dictionary", "to book; to reserve", "hanja form of X"
            if "hanja form of" in gloss or "alternative form" in gloss:
                continue
            # Clean up gloss
            en = gloss.split(";")[0].strip()
            en = re.sub(r'\s*\(.*?\)', '', en).strip()
            en = en.lower()
            if en and len(en) < 60 and not en.startswith("("):
                reverse[en].add(foreign_word)
    return {k: list(v) for k, v in reverse.items()}


def merge_en_translations(direct, reversed_dict):
    """Merge direct translations with reversed translations."""
    merged = defaultdict(list)

    # Add direct translations
    for word, items in direct.items():
        for item in items:
            merged[word].append(item["word"])

    # Add reversed translations
    for word, translations in reversed_dict.items():
        for t in translations:
            if t not in merged.get(word, []):
                merged[word].append(t)

    return dict(merged)


def build_dictionary():
    """Build the complete multilingual dictionary."""
    t0 = time.time()

    # Step 1: EN→KO/ZH from English.jsonl
    en_ko_direct, en_zh_direct = extract_en_translations()

    # Step 2: KO→EN, ZH→EN from raw-wiktextract
    ko_en, zh_en, ko_zh_direct, zh_ko_direct = extract_ko_zh_entries()

    # Step 3: Build reverse indices
    print()
    print("=" * 60)
    print("[3/4] Building reverse indices...")
    print("=" * 60)

    # Reverse KO→EN to get more EN→KO
    en_ko_reversed = build_reverse_index(ko_en)
    print(f"  EN→KO (reversed from KO→EN): {len(en_ko_reversed):,} words")

    # Reverse ZH→EN to get more EN→ZH
    en_zh_reversed = build_reverse_index(zh_en)
    print(f"  EN→ZH (reversed from ZH→EN): {len(en_zh_reversed):,} words")

    # Merge direct + reversed for EN→KO and EN→ZH
    en_ko_merged = merge_en_translations(en_ko_direct, en_ko_reversed)
    en_zh_merged = merge_en_translations(en_zh_direct, en_zh_reversed)
    print(f"  EN→KO (merged): {len(en_ko_merged):,} words")
    print(f"  EN→ZH (merged): {len(en_zh_merged):,} words")

    # Build KO→ZH and ZH→KO via English bridge
    print()
    print("  Building KO↔ZH via English bridge...")
    ko_zh_bridge = defaultdict(set)
    zh_ko_bridge = defaultdict(set)

    # For each KO word, find its English gloss, then find ZH words with same gloss
    for ko_word, entries in ko_en.items():
        for entry in entries:
            gloss = entry["gloss"].split(";")[0].strip().lower()
            gloss = re.sub(r'\s*\(.*?\)', '', gloss).strip()
            if gloss in en_zh_merged:
                for zh_word in en_zh_merged[gloss][:3]:
                    ko_zh_bridge[ko_word].add(zh_word)

    for zh_word, entries in zh_en.items():
        for entry in entries:
            gloss = entry["gloss"].split(";")[0].strip().lower()
            gloss = re.sub(r'\s*\(.*?\)', '', gloss).strip()
            if gloss in en_ko_merged:
                for ko_word in en_ko_merged[gloss][:3]:
                    zh_ko_bridge[zh_word].add(ko_word)

    # Merge direct + bridge
    for ko, zh_list in ko_zh_direct.items():
        for zh in zh_list:
            ko_zh_bridge[ko].add(zh)
    for zh, ko_list in zh_ko_direct.items():
        for ko in ko_list:
            zh_ko_bridge[zh].add(ko)

    print(f"  KO→ZH (bridge + direct): {len(ko_zh_bridge):,} words")
    print(f"  ZH→KO (bridge + direct): {len(zh_ko_bridge):,} words")

    # Step 4: Build final dictionary
    print()
    print("=" * 60)
    print("[4/4] Building final dictionary...")
    print("=" * 60)

    # Simplify KO→EN and ZH→EN for output (deduplicate glosses)
    def simplify_entries(entries_dict):
        result = {}
        for word, entries in entries_dict.items():
            glosses = []
            seen = set()
            for e in entries:
                g = e["gloss"]
                if g not in seen:
                    seen.add(g)
                    glosses.append({"gloss": g, "pos": e.get("pos", "")})
            result[word] = glosses[:5]  # Max 5 senses
        return result

    ko_en_simple = simplify_entries(ko_en)
    zh_en_simple = simplify_entries(zh_en)

    dictionary = {
        "metadata": {
            "version": "1.0",
            "source": "Wiktionary (kaikki.org extract)",
            "build_date": time.strftime("%Y-%m-%d"),
        },
        "stats": {
            "en_ko": len(en_ko_merged),
            "en_zh": len(en_zh_merged),
            "ko_en": len(ko_en_simple),
            "zh_en": len(zh_en_simple),
            "ko_zh": len(ko_zh_bridge),
            "zh_ko": len(zh_ko_bridge),
        },
        "en_ko": en_ko_merged,
        "en_zh": en_zh_merged,
        "ko_en": ko_en_simple,
        "zh_en": zh_en_simple,
        "ko_zh": {k: list(v) for k, v in ko_zh_bridge.items()},
        "zh_ko": {k: list(v) for k, v in zh_ko_bridge.items()},
    }

    # Save
    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(dictionary, f, ensure_ascii=False, indent=None)

    size_mb = OUTPUT.stat().st_size / 1024 / 1024
    elapsed = time.time() - t0

    print()
    print("=" * 60)
    print(f"DONE in {elapsed:.0f}s")
    print(f"Output: {OUTPUT} ({size_mb:.1f} MB)")
    print()
    print("Summary:")
    for pair, cnt in dictionary["stats"].items():
        print(f"  {pair}: {cnt:,} words")
    print("=" * 60)

    return dictionary


def lookup(word, dictionary=None):
    """Look up a word in all language pairs."""
    if dictionary is None:
        with open(OUTPUT, "r", encoding="utf-8") as f:
            dictionary = json.load(f)

    print(f"\n=== Lookup: {word} ===\n")
    found = False

    # Try EN→KO/ZH
    if word.lower() in dictionary.get("en_ko", {}):
        print(f"  EN→KO: {', '.join(dictionary['en_ko'][word.lower()][:5])}")
        found = True
    if word.lower() in dictionary.get("en_zh", {}):
        print(f"  EN→ZH: {', '.join(dictionary['en_zh'][word.lower()][:5])}")
        found = True

    # Try KO→EN/ZH
    if word in dictionary.get("ko_en", {}):
        glosses = [e["gloss"] for e in dictionary["ko_en"][word][:5]]
        print(f"  KO→EN: {'; '.join(glosses)}")
        found = True
    if word in dictionary.get("ko_zh", {}):
        print(f"  KO→ZH: {', '.join(dictionary['ko_zh'][word][:5])}")
        found = True

    # Try ZH→EN/KO
    if word in dictionary.get("zh_en", {}):
        glosses = [e["gloss"] for e in dictionary["zh_en"][word][:5]]
        print(f"  ZH→EN: {'; '.join(glosses)}")
        found = True
    if word in dictionary.get("zh_ko", {}):
        print(f"  ZH→KO: {', '.join(dictionary['zh_ko'][word][:5])}")
        found = True

    if not found:
        print("  (not found)")


def show_stats():
    """Show statistics of existing dictionary."""
    with open(OUTPUT, "r", encoding="utf-8") as f:
        d = json.load(f)
    print(f"\nMultilingual Dictionary Stats:")
    print(f"  Build date: {d['metadata']['build_date']}")
    for pair, cnt in d["stats"].items():
        print(f"  {pair}: {cnt:,} words")


if __name__ == "__main__":
    args = sys.argv[1:]

    if "--stats" in args:
        show_stats()
    elif "--lookup" in args:
        idx = args.index("--lookup")
        word = args[idx + 1] if idx + 1 < len(args) else ""
        lookup(word)
    else:
        build_dictionary()
