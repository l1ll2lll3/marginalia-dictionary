# 어휘 등급 목록 조사와 결정 (2026-10-17)

reading 리포(Marginalia)에서 진행한 논의를 옮겨 적었다. 단어마다 "얼마나 어려운가"를 붙이는 근거를 무엇으로 삼을지에 관한 내용이다.

---

## 1. 배경: 원래 "CEFR"은 가짜였다

Marginalia 책 데이터(`book_package.json`의 `vocabulary_index[*].difficulty`)에 붙어 있던 A1~C2는 진짜 CEFR이 아니었다. `wordfreq`의 Zipf 빈도를 구간으로 나누고 CEFR 이름만 붙인 것이었다 (`build_great_gatsby.py`의 `CEFR_THRESHOLDS`). 그래서 soldier, politician, belong처럼 빈도가 중간인 단어가 전부 B2에 몰렸다.

2026-09-28에 달과 6펜스를 CEFR-J + Octanove로 다시 매겼다 (`en-en/scripts/cefr_grading.py`).

| 결과 | 값 |
|---|---|
| 분포 | A1 512 · A2 656 · B1 894 · B2 707 · C1 928 · C2 1,019 |
| 근거 | cefr-j 58.1% · frequency 35.9% · octanove 5.4% · proper-noun 0.7% |
| B2 이상 문장 주석 | 8,630 → 5,237 (−39%) |

---

## 2. 영어 등급 목록

### CEFR-J 1.5 + Octanove 1.0 (현재 사용 중)

**단어 + 품사 한 쌍마다** CEFR 등급이 하나 붙어 있는 CSV다.

```
headword,pos,CEFR
cloak,noun,C1
```

| 목록 | 범위 | 규모 | 라이선스 |
|---|---|---|---|
| CEFR-J Wordlist 1.5 (도쿄외대 Tono 교수) | A1~B2 | 7,798행 | 연구·상업 이용 무료, 출처 표기 |
| Octanove Vocabulary Profile C1/C2 1.0 | C1~C2 | 2,136행 | CC BY-SA 4.0 |

- 둘을 합쳐도 약 1만 쌍이라 문학 어휘의 36%가 빠진다 (discern, pompous, capricious…).
- CEFR-J가 A1~B2를 다 담으므로, 목록에 없으면 구조상 "B2보다 어렵다"는 뜻이다.
- `adviser/advisor`처럼 슬래시로 묶은 이형이 167개 있고, Octanove에는 `vern` 오타가 1건 있다. `cefr_grading.py`에서 처리한다.

### 다른 영어 목록

| 목록 | 구분 | 장점 | 문제 |
|---|---|---|---|
| **English Vocabulary Profile** (Cambridge) | A1~C2, **뜻마다** (hunt: 쫓다 B1 · 찾다 B2 · 명사 C2) | 가장 정확함. 학습자 말뭉치 근거 | 웹에서 하나씩만 조회. 통째로 쓰는 약관은 확인 못 함 |
| **Oxford 3000/5000** | A1~C1 | 유명하고 학습자 사전과 연결됨 | OUP 저작권. 깃허브판은 비공식 |
| **Pearson GSE** | 10~90 점수 (CEFR보다 촘촘) | 약 36,000개 | 무료 웹 도구. 데이터 내려받기 가능 여부 미확인 |
| **NGSL 1.2** + NAWL·TSL·BSL | 등급 없음. 포함/불포함만 (핵심 2,809 · 학술 957 · 토익·비즈니스) | 실용적인 묶음 | 핵심 목록의 라이선스는 다시 확인 필요 |
| **습득 연령** (Kuperman 2012) | 원어민이 몇 살에 배우는지 | 약 3만 단어 | 원어민 기준이라 외국어 학습자와 다름 |

### 영어에는 왜 HSK 같은 공식 목록이 없나

- **HSK**: 중국 교육부·국가언어문자위원회 표준(HSK 3.0, GF0025-2021, 9단계 11,092단어)이다. 시험을 만드는 곳과 단어 목록을 정하는 곳이 같은 국가 기관이다.
- **영어**: 그런 단일 기관이 없다. CEFR(유럽평의회)은 일부러 언어 중립적인 능력 기술로 만들어졌고, 단어 목록이 없다. 언어별 목록은 각 나라나 기관이 따로 만든다.
  - 영어 쪽에서 그 역할에 가장 가까운 것이 Cambridge의 **English Profile (EVP)** 이다.
  - 그 밖에는 시험이나 교육과정마다 따로 목록이 있다: 한국 교육과정 기본어휘, 중국 高考·CET-4/6, 일본 JACET 8000·SVL 12000 등.
- 정리하면 "HSK처럼 공식이고 내려받을 수 있는 영어 등급 목록"은 없다. 공개 데이터 중에서는 CEFR-J + Octanove가 현실적인 최선이다.

---

## 3. 한국: 2022 개정 교육과정 영어과 기본 어휘

교육부 고시 제2022-33호 [별책 14] 영어과 교육과정 [별표 3] 어휘, pp. 254-290.

| 표시 | 개수 | 권장 학교급 |
|---|---|---|
| `*` | 800 | 초등학교 |
| `**` | 1,200 | 중학교 + 고등학교 공통영어 |
| (없음) | 1,000 | 고등학교 선택과목 (영어Ⅰ·Ⅱ, 영미 문학 읽기 등) |

- 수능 출제 어휘 범위도 이 목록을 따른다고 알려져 있다.
- **단어군 단위**다. 대표형이 굴절형 전부와 파생 접사 36개로 만든 변이형을 포함한다 (write → writes, wrote, written, writing / un-: unable, unhappy). 단, precious처럼 의존 어근에 접사가 붙은 말은 포함하지 않는다. 자주 쓰는 파생형은 괄호 안에 따로 적는다: `able** (disabled)`.
- 품사 구분이 없다.
- **저작권**: 국가의 고시는 저작권법 제7조에 따라 보호받지 않는 저작물이라 자유롭게 쓸 수 있다.
- 학년군별 학습 어휘 수 (누계): 초3~4 300 · 초5~6 300 (누계 600) · 중1~3 1,500 · 공통영어 1,800 · 영어Ⅰ 2,000 · 영어Ⅱ 2,500 · 영미 문학 읽기 3,000 · 심화 영어 독해와 작문 3,500.
- 원문 PDF: 경기도교육청 KICE Word Lister 안내서 (https://www.goe.go.kr/resource/old/BBSMSTR_000000030136/BBS_202307111028067791.pdf). 목록이 PDF 본문에 있어서, 3,000단어 · `*`/`**` 표시 · 괄호 속 파생어를 뽑아내는 작업이 필요하다.

고등학교 위로는 구분하지 않는다. 대학부터는 전공마다 쉽고 어려운 단어가 달라서 나누는 의미가 없다고 봤다 → **"교육과정 밖"** 하나로 묶는다.

---

## 4. 다른 언어

| 언어 | 목록 | 구분 |
|---|---|---|
| 한국어 | **KRDICT** (국립국어원 한국어기초사전) API의 어휘 등급 | 초급 · 중급 · 고급 |
| 한국어 | 국제 통용 한국어 표준 교육과정 어휘 (2017) | 초급 · 중급 · 고급 |
| 중국어 | **HSK 3.0** (2021) | 1~9급 |

KRDICT API 메모 (reading 리포에서 검증한 것):
- 키는 reading 리포의 `gutenberg/.env`에 `KRDICT_API_KEY`로 있다. 이 리포에는 복사하지 않았다.
- WAF가 기본 User-Agent를 막는다. 브라우저 UA를 넣지 않으면 `400 Request Blocked`가 난다.
- `num`은 10~100만 허용한다 (`num=1` → `error_code 103`).
- `https://krdict.korean.go.kr/api/search?key=…&q=…&translated=y&trans_lang=1&num=10`

---

## 5. 결정 사항

1. **사전에는 목록에 실제로 있는 단어 + 품사에만 등급을 적는다.** 나머지는 비워둔다.
   - 빈도로 C1/C2를 나누는 건 사실이 아니라 추정이다. 추정은 책 파이프라인이 학습 자료를 만들 때 하고, `cefr_source=frequency`로 표시한다.
2. **철자 변형과 굴절형은 원형의 등급을 물려받는다.** colour → color, went → go. Wiktionary의 "~의 다른 철자", "~의 과거형" 연결을 쓰고, 출처는 `inherited`로 따로 적는다.
3. **사전 등급은 기본값이고, 책에서 덮어쓸 수 있다.** presently가 옛 뜻("곧")으로 쓰였다면 그 책에서는 더 어렵다.
4. **등급 체계를 두 개 같이 둔다.**
   - 한국 교육과정 (초등 / 중고 공통 / 고교 선택 / 교육과정 밖): 한국 학습자에게 가장 직관적이다.
   - CEFR (CEFR-J + Octanove): 국제 기준이고, 다른 언어로 넓힐 때 쓴다.
   - 등급 체계가 앞으로 더 늘어날 수 있으므로 `words`에 칸을 계속 추가하지 않고 별도 표(`word_levels`)로 둔다 → `docs/schema.md`.
5. **라이선스.** Octanove는 CC BY-SA라서, DB를 통째로 공개 배포하면 그 DB도 같은 조건이 될 수 있다. 서버에서 조회 결과만 보여주는 지금 방식은 괜찮다. 앱에 DB를 넣을 때는 다시 확인한다.

## 출처

- 경기도교육청 — 2022 개정 영어과 교육과정 [별표 3] 어휘 / KICE Word Lister 안내서: https://www.goe.go.kr/resource/old/BBSMSTR_000000030136/BBS_202307111028067791.pdf
- 한국교육신문 — KICE 기본 어휘 개선 방안 연구: https://hangyo.com/news/article.html?no=109662
- Text Inspector — English Vocabulary Profile: https://textinspector.com/help/lexis-evp/
- Oxford 3000/5000: https://www.oxfordlearnersdictionaries.com/about/wordlists/oxford3000-5000
- Pearson GSE Teacher Toolkit 안내: https://www.pearsoncanadaschool.com/content/dam/websites/pearson-canada-school/assets/documents/literacy/gse/A-Guide-to-the-global-scale-of-english-teacher-toolkit.pdf
- New General Service List 1.2: https://www.newgeneralservicelist.com/new-general-service-list
- CEFR-J·Octanove 라이선스 메모: `en-en/data/cefr/LICENSE-NOTE.txt`
