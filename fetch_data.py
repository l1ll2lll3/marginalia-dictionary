#!/usr/bin/env python3
"""git에 넣지 않은 원본 데이터를 받는다.

    python fetch_data.py               # 기본: 사전 빌드에 꼭 필요한 것 (kaikki-en, 교육과정 PDF)
    python fetch_data.py --list        # 받을 수 있는 목록
    python fetch_data.py raw-wiktextract cedict
    python fetch_data.py --all
    python fetch_data.py kaikki-en --force   # 이미 있어도 새로 받기

받다가 끊기면 다시 실행하면 이어서 받는다 (`.part` 파일 + HTTP Range).
표준 라이브러리만 쓰므로 Windows에서도 그대로 돈다.
"""

import argparse
import shutil
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) MarginaliaDictionary/1.0"

# name: (url, 저장 위치, 대략 크기, 기본 포함, 설명)
TARGETS = {
    "kaikki-en": (
        "https://kaikki.org/dictionary/English/kaikki.org-dictionary-English.jsonl",
        "en-en/data/raw/kaikki-en.jsonl", "3.3GB", True,
        "영어 Wiktionary 전체 (kaikki). en-en 빌드, en-ko 추출에 필요",
    ),
    "kr-curriculum": (
        "https://www.goe.go.kr/resource/old/BBSMSTR_000000030136/BBS_202307111028067791.pdf",
        "en-en/data/raw/kr_curriculum_2022.pdf", "2.8MB", True,
        "2022 개정 영어과 기본 어휘 (KICE Word Lister 안내서). parse_kr_curriculum.py 입력",
    ),
    "raw-wiktextract": (
        "https://kaikki.org/dictionary/raw-wiktextract-data.jsonl.gz",
        "shared/data/raw/raw-wiktextract-data.jsonl.gz", "3.0GB", False,
        "전 언어 Wiktionary (gz). shared/build_multilingual_dict.py 입력",
    ),
    "ko-wiktionary": (
        "https://kaikki.org/kowiktionary/raw-wiktextract-data.jsonl.gz",
        "ko-ko/data/ko-extract.jsonl.gz", "27MB", False,
        "한국어 Wiktionary 추출. git에 이미 있음 — 갱신할 때만",
    ),
    "cedict": (
        "https://www.mdbg.net/chinese/export/cedict/cedict_1_0_ts_utf-8_mdbg.txt.gz",
        "zh-en/data/cedict_ts.txt.gz", "4MB", False,
        "CC-CEDICT 중영사전. git에 이미 있음 — 갱신할 때만",
    ),
    "cefrj": (
        "https://raw.githubusercontent.com/openlanguageprofiles/olp-en-cefrj/master/cefrj-vocabulary-profile-1.5.csv",
        "en-en/data/cefr/cefrj-vocabulary-profile-1.5.csv", "230KB", False,
        "CEFR-J 1.5 (A1~B2). git에 이미 있음",
    ),
    "octanove": (
        "https://raw.githubusercontent.com/openlanguageprofiles/olp-en-cefrj/master/octanove-vocabulary-profile-c1c2-1.0.csv",
        "en-en/data/cefr/octanove-vocabulary-profile-c1c2-1.0.csv", "46KB", False,
        "Octanove 1.0 (C1~C2). git에 이미 있음",
    ),
}


def _fmt(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f}{unit}" if unit != "B" else f"{n}B"
        n /= 1024


def download(name, force=False):
    url, rel, size, _, _ = TARGETS[name]
    dest = ROOT / rel
    part = dest.with_name(dest.name + ".part")
    dest.parent.mkdir(parents=True, exist_ok=True)

    if dest.exists() and not force:
        print(f"[{name}] 이미 있음 — 건너뜀 ({_fmt(dest.stat().st_size)}, --force로 새로 받기)")
        return
    if force and part.exists():
        part.unlink()

    done = part.stat().st_size if part.exists() else 0
    headers = {"User-Agent": UA}
    if done:
        headers["Range"] = f"bytes={done}-"
    print(f"[{name}] {url}\n    → {rel} (약 {size}){f', {_fmt(done)}부터 이어받기' if done else ''}")

    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=60) as response:
        if done and response.status != 206:      # 서버가 Range를 무시하면 처음부터
            done = 0
            part.unlink()
        total = response.length + done if response.length else None
        started, last, resumed_at = time.time(), 0.0, done
        with open(part, "ab") as out:
            while True:
                chunk = response.read(1 << 20)
                if not chunk:
                    break
                out.write(chunk)
                done += len(chunk)
                now = time.time()
                if now - last > 2:
                    last = now
                    rate = (done - resumed_at) / max(now - started, 1e-6)
                    pct = f"{done / total * 100:5.1f}% " if total else ""
                    print(f"    {pct}{_fmt(done)} · {_fmt(rate)}/s", flush=True)

    if total and done != total:
        raise SystemExit(f"[{name}] 크기가 맞지 않는다 ({done} / {total}). 다시 실행하면 이어받는다.")
    shutil.move(part, dest)
    print(f"[{name}] 완료 {_fmt(dest.stat().st_size)}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("names", nargs="*", help="받을 항목 (기본: 필수 항목만)")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--force", action="store_true", help="이미 있어도 새로 받는다")
    args = parser.parse_args()

    if args.list:
        for name, (_, rel, size, default, desc) in TARGETS.items():
            mark = "기본" if default else "    "
            have = "✓" if (ROOT / rel).exists() else " "
            print(f" {have} {mark} {name:<16} {size:>6}  {rel}\n{'':26}{desc}")
        return

    names = list(TARGETS) if args.all else (args.names or [n for n, t in TARGETS.items() if t[3]])
    unknown = [n for n in names if n not in TARGETS]
    if unknown:
        sys.exit(f"모르는 항목: {unknown} (--list로 확인)")
    for name in names:
        download(name, force=args.force)


if __name__ == "__main__":
    main()
