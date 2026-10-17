"""
merge_en_ko_dict.py — 여러 무료/기생성 소스를 합쳐 하나의 영→한 사전으로.

소스(우선순위 높은 순):
  1) Claude gloss 캐시 (gatsby/klara *_enrich_cache.json) — 어휘책용으로 정제된 뜻(고급어 커버)
  2) multilingual_dict.json en_ko (35,689) — 일상어
  3) en_ko_dict.json (kaikki, 2,058) — Wiktionary 번역
합본: gutenberg/en_ko_dict.json  (기존 kaikki판 덮어씀, 이게 '그 사전')

Usage: python merge_en_ko_dict.py
"""
import os, sys, json
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / "data" / "en_ko_dict.json"
# 책별 Claude gloss 캐시는 reading 리포에 있다
BOOKS_DIR = Path(os.environ.get("MARGINALIA_GUTENBERG", Path.home() / "reading" / "gutenberg"))


def norm_gloss(g):
    if isinstance(g, list):
        return [x for x in g if x]
    return [g] if g else []


def is_noise_key(word):
    """표제어가 아니라 영어 풀이 문장이 키로 새어 들어온 경우.
    예: "to be frequent, to be common", "an eagle or vulture." (multilingual_dict 유래)
    """
    return "," in word or word.endswith(".") or word.startswith("to ")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    merged = {}                                  # word -> {"ko":[...], "src":"..."}
    stats = {}

    def add(word, glosses, src):
        if not word or not word.isascii() or is_noise_key(word):
            return
        glosses = [g for g in glosses if g and any('가' <= c <= '힣' for c in g)]
        if not glosses:
            return
        e = merged.setdefault(word.lower(), {"ko": [], "src": src})
        for g in glosses:
            if g not in e["ko"]:
                e["ko"].append(g)
        stats[src] = stats.get(src, 0) + 1

    # 1) kaikki (낮은 우선순위 먼저 → 나중 소스가 앞에 보강)
    kaikki = HERE.parent / "data" / "en_ko_dict.json"
    if kaikki.exists():
        # 주의: OUT과 같은 파일 → 먼저 메모리에 읽고 나중에 덮어씀
        kd = json.load(open(kaikki, encoding="utf-8"))
        # 이미 merged 형식이면(재실행) 건너뜀
        if kd and isinstance(next(iter(kd.values())), dict) and "ko" in next(iter(kd.values())):
            for w, v in kd.items():
                add(w, v.get("ko", []), "kaikki")

    # 2) multilingual_dict en_ko
    md = HERE.parent.parent / "shared" / "data" / "multilingual_dict.json"
    if md.exists():
        d = json.load(open(md, encoding="utf-8"))
        enko = d.get("en_ko", {})
        for w, v in enko.items():
            add(w, norm_gloss(v), "multilingual_dict")

    # 3) Claude 캐시 (최우선 → ko 리스트 앞에 prepend)
    for cache in list(BOOKS_DIR.glob("*/*_enrich_cache.json")):
        try:
            c = json.load(open(cache, encoding="utf-8"))
        except Exception:
            continue
        for w, v in c.items():
            gl = norm_gloss(v.get("ko_gloss"))
            if not gl:
                continue
            e = merged.setdefault(w.lower(), {"ko": [], "src": "claude"})
            # Claude 뜻을 맨 앞에(가장 정제됨)
            for g in reversed(gl):
                if g in e["ko"]:
                    e["ko"].remove(g)
                e["ko"].insert(0, g)
            e["src"] = "claude" if e["ko"] else e["src"]
            stats["claude"] = stats.get("claude", 0) + 1

    json.dump(merged, open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"합본 사전: {len(merged):,} 표제어  ({OUT.stat().st_size/1e6:.1f}MB)")
    print("  소스별 기여:", stats)
    for w in ["supercilious", "florid", "benediction", "dilatory", "misgiving",
              "engross", "vulnerable", "happy"]:
        print(f"  {w:14} -> {merged.get(w, {}).get('ko', 'MISS')}")


if __name__ == "__main__":
    main()
