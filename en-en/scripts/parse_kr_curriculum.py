#!/usr/bin/env python3
"""2022 개정 영어과 교육과정 기본 어휘 3,000단어군을 PDF에서 뽑아 CSV로 만든다.

    python fetch_data.py kr-curriculum          # PDF 받기 (루트에서)
    python en-en/scripts/parse_kr_curriculum.py
    → en-en/data/kr_curriculum/moe_2022_basic_vocab.csv

원문 표기 (교육부 고시 제2022-33호 [별책 14] [별표 3]):
    a* (an)                       *  = 초등학교 (800)
    able** (disabled)             ** = 중학교 + 고등학교 공통과목 (1,200)
    abandon                       표시 없음 = 그 외 과목, 즉 고교 선택 (1,000)
    color* / colour*              / = 철자 이형. 같은 단어군
    consume** (consumer,          ( ) = 자주 쓰는 파생형. 줄을 넘겨 이어지기도 한다
     consumption)

CSV 한 행 = 표기 하나. 대표형, 철자 이형, 괄호 속 파생형을 모두 행으로 펼치고
`family`에 대표형을 적는다. 굴절형(went, books)과 36개 접사 파생형은 펼치지 않는다 —
그건 사전 빌드(build_levels.py)가 Wiktionary의 form-of 연결로 처리한다.
"""

import csv
import re
import sys
from collections import Counter
from pathlib import Path

EN_EN = Path(__file__).resolve().parent.parent
PDF = EN_EN / "data" / "raw" / "kr_curriculum_2022.pdf"
OUT = EN_EN / "data" / "kr_curriculum" / "moe_2022_basic_vocab.csv"

LEVELS = {"*": "elementary", "**": "middle_common", "": "high_elective"}
# 지침 본문의 숫자. 실제 목록에서 세면 elementary가 801이다 (중복·파싱 오류 없음을 확인함).
EXPECTED = {"elementary": 800, "middle_common": 1200, "high_elective": 1000}

# 목록은 "기본 어휘 목록" 제목 다음 "A"부터, 개정 내용 설명("II.") 앞까지다.
END_MARK = re.compile(r"^II\.\s")
NOISE = re.compile(r"^(<<PAGE \d+>>|- \d+ -|[A-Z]|기본 .*목.*)$")
TOKEN = re.compile(r"^([A-Za-z][A-Za-z'’.\- ]*?)\s*(\*{0,2})$")


def pdf_text(path):
    try:
        import pypdf
    except ImportError:
        sys.exit("pypdf가 필요하다: pip install pypdf")
    reader = pypdf.PdfReader(str(path))
    text = "\n".join(f"<<PAGE {i + 1}>>\n{page.extract_text() or ''}"
                     for i, page in enumerate(reader.pages))
    # PDF가 하이픈을 soft hyphen(U+00AD)으로 담고 있다 (half­moon)
    return text.replace("­", "-").replace("’", "'")


def list_lines(text):
    """목록 구간의 줄만, 괄호가 닫힐 때까지 이어 붙여서 돌려준다."""
    lines = text.splitlines()
    start = next(i for i, l in enumerate(lines)
                 if l.strip() == "A" and i + 1 < len(lines) and lines[i + 1].strip().startswith("a*"))
    entries, buf = [], ""
    for raw in lines[start:]:
        line = raw.strip()
        if END_MARK.match(line):
            break
        if not line or NOISE.match(line):
            continue
        # "communicate**" 다음 줄에 "(communication)"만 오는 경우 — 앞 항목에 붙인다
        if not buf and line.startswith("(") and entries:
            buf = entries.pop()
        buf = f"{buf} {line}".strip() if buf else line
        if buf.count("(") <= buf.count(")"):
            entries.append(buf)
            buf = ""
    if buf:
        entries.append(buf)
    return entries


def parse_entry(entry):
    """'consume** (consumer, consumption)' → (대표형들, 등급표시, 파생형들)"""
    head, _, rest = entry.partition("(")
    derivatives = []
    if rest:
        inner = rest.rsplit(")", 1)[0]
        derivatives = [d.strip() for d in re.split(r"[,/]", inner) if d.strip()]

    forms, stars = [], None
    for part in head.split("/"):
        part = part.strip()
        if not part:
            continue
        match = TOKEN.match(part)
        if not match:
            raise ValueError(f"해석 불가: {entry!r}")
        forms.append(match.group(1).strip())
        stars = match.group(2) if stars is None else stars
    return forms, stars or "", derivatives


def main():
    if not PDF.exists():
        sys.exit(f"PDF가 없다: {PDF}\n  루트에서 python fetch_data.py kr-curriculum")

    rows, families = [], Counter()
    for entry in list_lines(pdf_text(PDF)):
        forms, stars, derivatives = parse_entry(entry)
        level = LEVELS[stars]
        family = forms[0]
        families[level] += 1
        for i, form in enumerate(forms):
            rows.append({"word": form, "level": level, "family": family,
                         "kind": "headword" if i == 0 else "spelling_variant"})
        for derivative in derivatives:
            rows.append({"word": derivative, "level": level, "family": family,
                         "kind": "derivative"})

    print("단어군 수 (기대값):")
    for level, n in EXPECTED.items():
        mark = "✓" if families[level] == n else "✗"
        print(f"  {mark} {level:<14} {families[level]:>5}  ({n})")
    print(f"  행 {len(rows):,} (대표형 {sum(families.values()):,} + 이형·파생형)")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["word", "level", "family", "kind"])
        writer.writeheader()
        writer.writerows(rows)
    print(f"저장: {OUT.relative_to(EN_EN.parent)}")


if __name__ == "__main__":
    main()
