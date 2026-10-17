#!/usr/bin/env python3
"""Wiktionary(kaikki)에서 품사별 미국식 발음을 뽑아 캐시로 저장한다.

기존 `enrich_vocabulary.py`는 단어의 첫 항목만 가져오면서 품사를 구분하지 않았다.
그래서 refuse가 동사로 태깅됐는데 명사 발음 /ˈɹɛfjuːs/이 붙는 식의 오류가 생겼고,
US 태그가 없으면 첫 발음(주로 영국식)을 그대로 써서 한 책 안에 미국식과 영국식이
섞였다 (달과 6펜스: US 기호 257 · UK 기호 332).

여기서는 (단어, 품사)별로 뽑고, 미국식을 우선하며, 음소 표기 /.../ 만 쓴다.

사용법:
    python extract_pronunciations.py --book the_moon_and_sixpence/book_package.json
    python extract_pronunciations.py --book ... --source ~/kaikki.jsonl   # 로컬 파일

원본은 3.3GB라 내려받지 않고 흘려보내며 필요한 단어만 거른다. 결과는
pronunciations_en.json에 누적되므로 두 번째 책부터는 이미 받은 단어를 건너뛴다.
"""

import io
import re
import unicodedata
import json
import gzip
import argparse
import collections
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
CACHE_PATH = BASE_DIR / "data" / "build" / "pronunciations_en.json"
LOCAL_KAIKKI = BASE_DIR / "data" / "raw" / "kaikki-en.jsonl"
KAIKKI_URL = "https://kaikki.org/dictionary/English/kaikki.org-dictionary-English.jsonl"

# kaikki 품사 → 우리 품사
POS_FROM_KAIKKI = {
    "noun": "NOUN",
    "verb": "VERB",
    "adj": "ADJ",
    "adv": "ADV",
}

# 발음 변종 우선순위. 앞쪽일수록 먼저 채택한다.
# 한 책 안에서 표기를 통일하는 것이 목적이라 미국식으로 고정한다.
US_TAGS = ("General-American", "GenAm", "US", "American", "Canada")
STRONG_US_TAGS = ("General-American", "GenAm", "US", "American")
UK_TAGS = ("Received-Pronunciation", "RP", "UK", "British", "England")

# 미국·영국 표준도 아니고 방언도 아닌, 발음 특징만 표시하는 태그.
# 이 태그만 달린 후보는 "태그 없음"과 같게 본다.
NEUTRAL_TAGS = ("cot-caught-merger", "pin-pen-merger", "Mary-marry-merry-merger",
                "father-bother-merger", "horse-hoarse-merger", "wine-whine-merger",
                "Standard", "standard", "General", "Southern", "Western", "weak", "strong", "stressed",
                "unstressed", "emphatic", "colloquial", "rhotic", "non-rhotic")

# 지역 방언 판정은 허용 목록 방식이다 (_variety): 미국·영국·중립 태그가 아닌 태그가
# 하나라도 붙으면 방언으로 본다.
#
# 처음에는 방언 태그를 나열했다. 그랬더니 목록에 없는 지역이 계속 "태그 없음"으로
# 가산점을 받았다 — cook /kʉk/(Scotland), fish /fɘʃ/(New-Zealand), fall /faːl/(Northumbria).
# 아래 목록은 build_levels 등 다른 곳에서 참고용으로만 쓴다.
DIALECT_TAGS = ("Australia", "New-Zealand", "Scotland", "Wales", "Ireland",
                "Northern-England", "Southern-US", "India", "South-Africa",
                "Singapore", "Philippines", "Nigeria", "AAVE", "Cockney",
                "Estuary-English", "Multicultural-London-English")

# note 칸 해석. 새 덤프는 억양 정보를 태그 대신 note에 적는 경우가 많다.
#
# 1) 지역·집단 이름이 있으면 방언이다. US·UK·RP·Canada 외의 대문자 단어로 판단한다.
#      "Midland US, Southern US" (but /ˈbɜt/), "Upper Midwestern US" (egg /eɪ̯ɡ/),
#      "Baltimore, Philadelphia", "South Wales", "African-American Vernacular"
# 2) 명시적으로 미국·영국을 적은 경우: "yod-dropping, US, Canada" / "…, Received Pronunciation"
# 3) 영국식 특징: non-rhotic, yod-coalescence
# 4) 자음 탈락: nt-flapping, t-glottalization (단 "without …"은 표준형)
# 5) 나머지는 발음 특징 설명이라 중립: "stressed form", "happy-tensing", "rhotic",
#    "without the cot–caught merger"
#
# "rhotic"을 미국식 신호로 쳤다가 plumber가 b를 발음하는 /ˈplʌm.bʌɾ/로 들어갔다.
NOTE_ALLOWED_NAMES = {"US", "UK", "RP", "Received", "Pronunciation", "General", "American",
                      "Canada", "Canadian", "British", "English"}
NOTE_NAME = re.compile(r"\b[A-Z][A-Za-z-]*")
# 하이픈으로 이은 발음 현상 이름(Mary–marry–merry merger, th-fronting)은 지역명이 아니다
NOTE_PHENOMENON = re.compile(r"[\w/]+(?:[–-][\w/]+)+")
NOTE_US = re.compile(r"\bUS\b|General American|Canad|yod-dropping")
NOTE_UK = re.compile(r"Received Pronunciation|\bUK\b|\bRP\b|British|non-rhotic|yod-coalescence",
                     re.IGNORECASE)
NOTE_REDUCED = re.compile(r"^(?!without).*(flapping|glottal|elision)", re.IGNORECASE)

# 태그에 이게 있으면 미국 태그가 같이 있어도 표준형이 아니다
# (terrible의 /ˈtɝ.bəl/은 [US, archaic, dialectal]).
#
# "dialectal"은 넣지 않는다. 이 덤프는 미국 표준형에도 붙인다 — profit의 /ˈpɹɑfɪt/이
# [General-American, dialectal] + note "of Canada"다. 넣었더니 영국식 /ˈpɹɒfɪt/이 뽑혔다.
NONSTANDARD_TAGS = {"archaic", "obsolete", "dated", "rare", "nonstandard",
                    "uncommon", "proscribed", "humorous", "eye-dialect"}

# 미국식 표기에만 나오는 r음화 모음
US_SYMBOLS = re.compile(r"[ɚɝ]")

# tr·dr 파찰음화 (/t͡ʃɹ/, /d͡ʒɹ/). 철자와 상관없이 구어 변종이다.
# interesting은 철자에 ti가 있어서 철자 검사를 통과해버렸다.
TR_AFFRICATION = re.compile(r"(t͡ʃ|tʃ|d͡ʒ|dʒ)ɹ")


# 파찰음 /t͡ʃ/·/d͡ʒ/을 정당화하는 철자. 이게 없는데 발음에 파찰음이 있으면
# 방언 변종(tr→[tʃɹ] 파찰음화)일 가능성이 높다.
# soldier의 -dier, picture의 -tu-, question의 -ti- 처럼 구개음화로 파찰음이
# 생기는 철자까지 포함한다. 빠뜨리면 정당한 발음이 감점된다.
AFFRICATE_GRAPHEMES = ("ch", "tch", "j", "dg", "dj", "ge", "gi", "gy",
                       "tu", "du", "ti", "di", "ci", "si", "su")
AFFRICATES = ("t͡ʃ", "tʃ", "d͡ʒ", "dʒ")

# 표기 내용으로 드러나는 영국식 신호. 태그가 없어도 ɒ·əʊ가 있으면 영국식이다.
# fall이 /fɒl/, doctor가 /ˈdɒktəɹ/로 들어간 것이 이 경우였다.
UK_SYMBOLS = re.compile(r"ɒ|əʊ|ɜː|ɪə|eə|ʊə")

# 철자 변형 안내문에서 원형을 뽑는다. colour 항목에는 구조화된 alt_of가 없고
# 뜻풀이에 "Commonwealth and Ireland standard spelling of color."라고만 적혀 있다.
VARIANT_GLOSS = re.compile(
    r"\b(?:standard|alternative|alternate|archaic|obsolete|dated|british|american|"
    r"commonwealth|uk|us|common)?\s*spelling\s+of\s+([A-Za-z][A-Za-z'\-]*)",
    re.IGNORECASE,
)

# 철자 변형이 아닌 참조. 태그로 걸러낸다.
#
# "form of"까지 넓게 잡았다가 ami←amigurumi(약어)와 adventured←adventure(굴절형)가
# 딸려 들어왔다. 굴절형에 원형 발음을 붙이면 adventured가 /ədˈvɛn.t͡ʃɚ/가 되어
# 끝의 -d가 사라진다 — 리포트 3번과 같은 유형의 오류다.
NOT_A_SPELLING_VARIANT = {
    "form-of", "participle", "past", "plural", "singular", "comparative",
    "superlative", "abbreviation", "clipping", "initialism", "acronym",
    "contraction", "gerund", "present", "third-person",
}

STRIP_FOR_COMPARE = str.maketrans("", "", "ˈˌ.ː ͡/")
VOWELS = set("aeiouyəɪʊɛɔæɑɒʌɜɐɚɝøœɘʉɵɨʏɤɯɞɶ")


def _base(ipa):
    """비교용: 구별 부호(결합 문자)를 뗀다. /fɪ̝ʃ/ → /fɪʃ/"""
    return "".join(ch for ch in unicodedata.normalize("NFD", ipa)
                   if not unicodedata.combining(ch))


def _consonant_count(ipa):
    # ː·ʰ·ʲ 같은 수식 문자(Lm)는 isalpha()가 참이라 따로 뺀다.
    # ɚ·ɝ는 모음 + r이므로 r 하나로 센다 — 안 그러면 /ˈwɔ.tɚ/가 /ˈwʊ.təɹ/에 진다.
    base = _base(ipa)
    return sum(1 for ch in base
               if ch.isalpha() and ch not in VOWELS and unicodedata.category(ch) != "Lm") \
        + sum(base.count(ch) for ch in "ɚɝ")


def _variety(tags, note=None):
    """(변종, 가산점).

    - 비표준 표시(archaic, dialectal …)가 있으면 방언이다.
    - 표준 태그(General-American, RP …)가 있으면 다른 지역이 같이 붙어 있어도 표준형이다
      — button의 /ˈbʌtən/은 [General-American, Received-Pronunciation, Southern-England].
    - 표준 태그 없이 다른 지역 태그가 붙으면 방언이다 — tune의 /tɪu̯n/은 [Canada, Wales].
    - Canada만 붙은 것은 미국식으로 치지 않고 중립으로 본다. awake의 /əˈweːk/처럼
      캐나다 고유 발음이 미국 가산점을 받아 표준형 /əˈweɪk/을 이기는 일이 있었다.
    - 태그가 없으면 note를 읽는다 (위 NOTE_* 설명).
    """
    if tags & NONSTANDARD_TAGS:
        return "dialect", -4.0
    if tags & set(STRONG_US_TAGS):
        return "us", 2.0
    # British Southern Standard는 새 영국식 표기 체계(/foːl/, /n(j)ʉw/)라 전통 RP보다 뒤에 둔다
    if {"British", "Southern", "Standard"} <= tags:
        return "uk", -1.0
    if tags & set(UK_TAGS):
        return "uk", 0.0
    if tags - set(US_TAGS) - set(NEUTRAL_TAGS) - {"dialectal"}:
        return "dialect", -4.0
    if note:
        names = set(NOTE_NAME.findall(NOTE_PHENOMENON.sub("", note))) - NOTE_ALLOWED_NAMES
        if names:
            return "dialect", -4.0
        if NOTE_REDUCED.search(note):
            return "unknown", -2.0
        if NOTE_UK.search(note):
            return "uk", 0.0
        if NOTE_US.search(note):
            return "us", 2.0
    bonus = 0.0 if tags & {"unstressed", "weak"} else 1.0
    return "unknown", bonus


def _score(ipa, word):
    """같은 태그를 가진 후보들 중 표준형을 고르기 위한 점수.

    Wiktionary는 방언·구어 변종을 표준형과 **같은 태그로** 함께 싣는다.
    trouble에는 /ˈt͡ʃɹʌbəl/(파찰음화)와 /ˈtɹʌbəl/(표준형)이 둘 다
    [Canada, General-American, Received-Pronunciation]로 달려 있어서
    태그만으로는 가릴 수 없다. 첫 번째를 집으면 방언형이 들어간다.
    """
    score = 0.0
    lowered = word.lower()

    # 철자에 근거 없는 파찰음 — trouble의 /t͡ʃ/가 여기 걸린다
    if any(a in ipa for a in AFFRICATES):
        if not any(g in lowered for g in AFFRICATE_GRAPHEMES) or TR_AFFRICATION.search(ipa):
            score -= 10.0

    # 괄호는 선택적 분절 표기 — /kənˈt(ʃ)ɹæst/. 감점이 미국식 가산점보다 크면
    # mountain의 미국식 /ˈmaʊn.t(ə)n/이 영국식에 진다.
    if "(" in ipa or ")" in ipa:
        score -= 1.5

    # 미국식으로 통일하는 것이 목적이므로 영국식 기호는 감점한다.
    # 미국식 표기가 아예 없는 단어(apéritif, aunt)에서는 그래도 최선이라 선택된다.
    if UK_SYMBOLS.search(ipa):
        score -= 2.5

    # 반대로 ɚ·ɝ는 미국식 표기다.
    # (장음 기호 ː 감점도 시험했다가 뺐다 — view가 /vjuː/ 대신 웨일스식 /vɪu̯/로 갔다.)
    if US_SYMBOLS.search(ipa):
        score += 0.5

    # 자음이 더 많은 쪽을 선호한다. painting의 /ˈpeɪ.nɪŋ/은 표준형
    # /ˈpeɪn.tɪŋ/에서 t가 탈락한 축약형이라 자음이 하나 적다.
    score += _consonant_count(ipa) * 0.5
    return score


def _is_reduction(shorter, longer):
    """shorter가 longer에서 **자음**을 뺀 축약형인지 (painting의 t 탈락).

    빠진 것이 모음이나 j뿐이면 축약이 아니다. 미국식 /ˈstu.dn̩t/은 /ˈstjuː.dn̩t/의
    부분수열이지만 yod 탈락이라는 억양 차이다. 구별 부호만 다른 경우(/fɪʃ/ vs 호주식
    /fɪ̝ʃ/)도 축약이 아니다.
    """
    a = _base(shorter).translate(STRIP_FOR_COMPARE)
    b = _base(longer).translate(STRIP_FOR_COMPARE)
    if len(a) >= len(b):
        return False
    dropped, i = [], 0
    for ch in b:
        if i < len(a) and a[i] == ch:
            i += 1
        else:
            dropped.append(ch)
    if i < len(a):                      # 부분수열이 아니다
        return False
    return any(ch.isalpha() and ch not in VOWELS and ch != "j"
               and unicodedata.category(ch) != "Lm" for ch in dropped)


def _pick_ipa(sounds, word):
    """음소 표기 중 표준형을 고른다.

    버킷 우선순위(US 먼저)로 뽑으면 안 된다. painting에는
    /ˈpeɪn.tɪŋ/(태그 없음, 표준형)과 /ˈpeɪ.nɪŋ/(US 태그, 구어 축약형)이 있는데
    US를 무조건 앞세우면 축약형이 이긴다.

    그래서 전부 한자리에 놓고 점수로 고른다. 미국식 선호는 가산점으로만 반영한다.
    """
    candidates = []
    for sound in sounds or []:
        ipa = (sound.get("ipa") or "").strip()
        if not ipa or not ipa.startswith("/"):
            continue
        # "/ˈtwɛnti/ [-ɛɾ̃i]"처럼 정밀 표기가 한 칸에 붙어 오는 경우가 있다
        ipa = ipa[:ipa.index("/", 1) + 1] if "/" in ipa[1:] else ipa
        variety, bonus = _variety(set(sound.get("tags") or []), sound.get("note"))
        candidates.append([ipa, variety, bonus])

    if not candidates:
        return None, None

    # 표준 태그(us/uk)가 붙은 후보가 있으면 태그 없는 후보는 오히려 약간 감점한다.
    # 그런 단어에서 태그 없는 후보는 대개 뒤에 덧붙인 부차 변형이다 — thank에는
    # RP /ˈθæŋk/ 뒤에 태그 없는 /ˈðæŋk/·/ˈθeɪŋk/가 있다.
    if any(variety in ("us", "uk") for _, variety, _ in candidates):
        for c in candidates:
            if c[1] == "unknown" and c[2] > 0:
                c[2] = -0.5

    # ː만 다른 쌍이면 ː 없는 쪽(미국식 표기)을 고른다 — fall /fɔːl/ vs /fɔl/
    bare = {ipa.replace("ː", "") for ipa, _, _ in candidates if "ː" not in ipa}
    for c in candidates:
        if "ː" in c[0] and c[0].replace("ː", "") in bare:
            c[2] -= 1.0


    # 축약 판정의 기준이 되는 "멀쩡한" 후보들. 파찰음·괄호로 감점된 것은 제외한다.
    #
    # 그냥 "다른 후보의 부분수열이면 감점"으로 하면 역효과가 난다. trouble의
    # 올바른 /ˈtɹʌbəl/은 잘못된 /ˈt͡ʃɹʌbəl/의 부분수열이라 감점당하고, 결국
    # 엉뚱한 방언형 /ˈtɹʊbəl/(Northern-England)이 뽑힌다.
    # 방언형과 영국식도 기준에서 뺀다 — 그보다 짧다는 이유로 미국 표준형이 감점되면
    # 안 된다. new의 미국식 /nu/는 영국식 /njuː/의 부분수열이지만 축약이 아니라
    # 억양 차이(yod 탈락)다.
    clean = [ipa for ipa, variety, _ in candidates
             if variety not in ("dialect", "uk") and _score(ipa, word) >= 0]

    best, best_score = None, None
    for ipa, variety, bonus in candidates:
        score = _score(ipa, word) + bonus
        if any(_is_reduction(ipa, other) for other in clean if other != ipa):
            score -= 6.0
        if best_score is None or score > best_score:
            best, best_score = (ipa, variety), score
    return best


def _variant_target(entry):
    """이 항목이 다른 **철자**의 변형이면 그 원형을 돌려준다 (colour → color).

    굴절형(adventured)과 약어(ami)는 제외한다. 발음이 원형과 다르기 때문이다.
    """
    for sense in entry.get("senses") or []:
        tags = {t.lower() for t in (sense.get("tags") or [])}
        if tags & NOT_A_SPELLING_VARIANT:
            continue

        for gloss in sense.get("glosses") or []:
            match = VARIANT_GLOSS.search(gloss)
            if match:
                return match.group(1).strip().rstrip(".")

        # 태그가 철자 변형임을 명시한 경우만 구조화 필드를 따른다
        if "alt-of" in tags:
            for ref in sense.get("alt_of") or []:
                target = (ref.get("word") or "").strip()
                if target:
                    return target
    return None


def wanted_lemmas(book_path):
    package = json.load(open(book_path, encoding="utf-8"))
    return set(package.get("vocabulary_index", {}))


def open_stream(source):
    if source:
        path = Path(source)
        if path.suffix == ".gz":
            return gzip.open(path, "rt", encoding="utf-8")
        return open(path, encoding="utf-8")

    request = urllib.request.Request(KAIKKI_URL, headers={"User-Agent": "Mozilla/5.0"})
    response = urllib.request.urlopen(request)
    return io.TextIOWrapper(response, encoding="utf-8", errors="replace")


def harvest(lemmas, source=None, progress_every=400_000):
    """스트림을 훑어 (단어, 품사) → 발음을 모은다.

    발음이 없는 항목은 철자 변형일 수 있다 (colour는 IPA 없이 "standard spelling
    of color"라고만 적혀 있다). 그런 항목의 원형을 모아 2패스에서 해결한다.
    """
    lower = {l.lower(): l for l in lemmas}
    found = {}
    variants = {}          # 우리 표제어 → 참조할 원형 (colour → color)
    variety_count = collections.Counter()
    seen = 0

    with open_stream(source) as stream:
        for line in stream:
            seen += 1
            if seen % progress_every == 0:
                print(f"    {seen:,}행 · 수집 {len(found):,}", flush=True)
            if '"word"' not in line:
                continue
            try:
                entry = json.loads(line)
            except ValueError:
                continue

            word = (entry.get("word") or "").lower()
            if word not in lower:
                continue
            pos = POS_FROM_KAIKKI.get(entry.get("pos"))
            if not pos:
                continue

            ours = lower[word]
            key = f"{ours}|{pos}"
            if key in found:
                continue

            ipa, variety = _pick_ipa(entry.get("sounds"), word)
            if ipa:
                found[key] = {"ipa": ipa, "variety": variety}
                variety_count[variety] += 1
                continue

            target = _variant_target(entry)
            if target and target.lower() != word:
                variants.setdefault(ours, target)

    print(f"    총 {seen:,}행 훑음")
    return found, variants, variety_count


def resolve_variants(variants, source=None):
    """철자 변형의 원형 발음을 가져온다 (colour ← color의 발음).

    원형은 우리 표제어 목록에 없을 수 있으므로 별도로 한 번 더 훑는다.
    """
    if not variants:
        return {}

    targets = {t.lower(): t for t in variants.values()}
    pronunciations = {}
    with open_stream(source) as stream:
        for line in stream:
            if '"word"' not in line:
                continue
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            word = (entry.get("word") or "").lower()
            if word not in targets:
                continue
            pos = POS_FROM_KAIKKI.get(entry.get("pos"))
            if not pos:
                continue
            key = f"{word}|{pos}"
            if key in pronunciations:
                continue
            ipa, variety = _pick_ipa(entry.get("sounds"), word)
            if ipa:
                pronunciations[key] = {"ipa": ipa, "variety": variety}

    resolved = {}
    for ours, target in variants.items():
        for pos in POS_FROM_KAIKKI.values():
            hit = pronunciations.get(f"{target.lower()}|{pos}")
            if hit:
                resolved[f"{ours}|{pos}"] = dict(hit, variant_of=target)
    return resolved


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--book", required=True, help="book_package.json 절대경로 (reading 리포)")
    parser.add_argument("--source", default=str(LOCAL_KAIKKI) if LOCAL_KAIKKI.exists() else None,
                        help="로컬 kaikki jsonl(.gz) 경로 (기본: data/raw/kaikki-en.jsonl, 없으면 스트리밍)")
    parser.add_argument("--cache", default=str(CACHE_PATH))
    args = parser.parse_args()

    book_path = Path(args.book)
    if not book_path.is_absolute() and not book_path.exists():
        book_path = BASE_DIR / args.book

    cache_path = Path(args.cache)
    cache = json.load(open(cache_path, encoding="utf-8")) if cache_path.exists() else {}
    print(f"기존 캐시 {len(cache):,}건")

    lemmas = wanted_lemmas(book_path)
    have = {k.split("|")[0] for k in cache}
    todo = {l for l in lemmas if l not in have}
    print(f"이 책 표제어 {len(lemmas):,} · 새로 받을 단어 {len(todo):,}")

    if not todo:
        print("받을 것이 없다.")
        return

    print("  Wiktionary 1패스: 발음 수집")
    found, variants, variety = harvest(todo, args.source)

    if variants:
        print(f"  철자 변형 {len(variants)}건 — 2패스로 원형 발음 조회")
        print(f"    예) {list(variants.items())[:4]}")
        resolved = resolve_variants(variants, args.source)
        # 이미 자기 발음을 찾은 항목은 건드리지 않는다.
        #
        # 한 단어에 kaikki 항목이 여러 개 있어서, 발음 없는 항목(주로 주변적인
        # 뜻)에서 변형 링크를 기록해두고 나중에 진짜 발음을 찾는 일이 생긴다.
        # 그대로 덮어쓰면 loss가 lost의 발음을, jest가 just의 발음을 갖게 된다.
        applied = {k: v for k, v in resolved.items() if k not in found}
        print(f"    해결 {len(resolved)}건 · 실제 적용 {len(applied)}건 "
              f"(자기 발음이 있는 {len(resolved) - len(applied)}건은 유지)")
        found.update(applied)

    cache.update(found)
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=0, sort_keys=True)

    print(f"\n새로 수집 {len(found):,} · 캐시 총 {len(cache):,}")
    print(f"  발음 변종: {dict(variety)}")
    covered = {k.split('|')[0] for k in found}
    print(f"  단어 기준 적중 {len(covered):,} / {len(todo):,}")
    print(f"저장: {cache_path.name}")


if __name__ == "__main__":
    main()
