"""
build_en_ko_dict.py — kaikki(Wiktionary) 영어 jsonl에서 영→한 사전을 추출.

각 영어 표제어의 translations 중 한국어(code=ko / lang=Korean)를 모아
en_ko_dict.json 로 저장. 어휘책 ko_gloss 를 Claude 대신 이 사전에서 조회(무료·결정적).

산출물: gutenberg/en_ko_dict.json  { "supercilious": {"ko": ["거만한", ...], "pos": ["adj"]}, ... }

Usage: python build_en_ko_dict.py
"""
import sys, json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
KAIKKI = ROOT / "en-en" / "data" / "raw" / "kaikki-en.jsonl"
OUT = HERE.parent / "data" / "en_ko_dict.json"


def is_hangul(s):
    return any('가' <= c <= '힣' for c in s)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    if not KAIKKI.exists():
        print(f"kaikki 없음: {KAIKKI}"); return
    d = {}
    n_lines = n_hit = 0
    with open(KAIKKI, encoding="utf-8") as f:
        for line in f:
            n_lines += 1
            # 빠른 사전필터: 한국어 번역이 있을 가능성 있는 줄만 파싱
            if '"translations"' not in line:
                continue
            if '"ko"' not in line and 'Korean' not in line:
                continue
            try:
                o = json.loads(line)
            except Exception:
                continue
            w = o.get("word")
            if not w or not w.isascii():
                continue
            pos = o.get("pos")
            for t in o.get("translations", []):
                if t.get("code") == "ko" or t.get("lang") == "Korean":
                    kw = (t.get("word") or "").strip()
                    if kw and is_hangul(kw):
                        e = d.setdefault(w, {"ko": [], "pos": []})
                        if kw not in e["ko"]:
                            e["ko"].append(kw)
                        if pos and pos not in e["pos"]:
                            e["pos"].append(pos)
                        n_hit += 1
            if n_lines % 500000 == 0:
                print(f"  ...{n_lines:,} 줄, 표제어 {len(d):,}")

    json.dump(d, open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
    mb = OUT.stat().st_size / 1e6
    multi = sum(1 for v in d.values() if len(v["ko"]) > 1)
    print(f"\n완료: {len(d):,} 영어 표제어 → 한국어  (번역쌍 {n_hit:,})")
    print(f"  복수 뜻 보유: {multi:,}")
    print(f"  저장: {OUT.name}  ({mb:.1f}MB)")
    # 샘플 (고급어 확인)
    for w in ["supercilious", "florid", "benediction", "dilatory", "misgiving", "engross"]:
        print(f"  {w:14} -> {d.get(w, {}).get('ko', 'MISS')}")


if __name__ == "__main__":
    main()
