# Marginalia Dictionary

Marginalia(문학으로 언어를 배우는 읽기 도구)에서 쓰는 사전을 만드는 프로젝트다. 2026-10-17에 reading 리포(`~/reading/gutenberg/`)에서 떼어냈다.

책 파이프라인(reading)은 이 사전이 만든 결과를 **가져다 쓰는 쪽**이고, 사전 자체를 만들고 고치는 일은 여기서 한다.

- 운영 중: **Marginalia Dictionary** https://marginalia-dict.fly.dev/ (en-en, Fly.io 앱 `marginalia-dict`)

---

## 언어쌍 9개

폴더 이름은 `표제어언어-풀이언어`다. `en-ko`는 영어 단어를 한국어로 풀이하는 영한사전이다.

| 폴더 | 사전 | 현재 상태 | 가진 것 |
|---|---|---|---|
| `en-en` | 영영 | ✅ 운영 중 | Wiktionary 원본 3.1GB, `dict.db`, 웹앱, 등급 목록, 발음 추출기 |
| `en-ko` | 영한 | 🟡 JSON | `en_ko_dict.json` 20,286개 + 빌드·병합 스크립트 |
| `en-zh` | 영중 | 🟡 JSON | `shared/data/multilingual_dict.json`의 `en_zh` 129,551개 |
| `ko-en` | 한영 | 🟡 JSON | `multilingual_dict.json`의 `ko_en` 45,112개. KRDICT API 예정 |
| `ko-ko` | 한한 | 🟡 원본만 | 한국어 Wiktionary 추출 `ko-extract.jsonl.gz` 355,243개. KRDICT 예정 |
| `ko-zh` | 한중 | 🟡 JSON | `multilingual_dict.json`의 `ko_zh` 15,473개 |
| `zh-en` | 중영 | 🟡 원본 + JSON | CC-CEDICT `cedict_ts.txt.gz` 124,380개, `zh_en` 168,057개 |
| `zh-ko` | 중한 | 🟡 JSON | `multilingual_dict.json`의 `zh_ko` 45,020개 |
| `zh-zh` | 중중 | ⬜ 없음 | — |

`shared/`에는 여러 언어쌍을 한 번에 만드는 스크립트(`build_multilingual_dict.py`)와 그 결과가 있다.

---

## 폴더 구조

```
marginalia-dictionary/
├── README.md               ← 이 파일
├── CLAUDE.md               ← Claude Code 세션용 컨텍스트
├── requirements.txt
├── fetch_data.py           ← git에 없는 원본 받기
├── docs/
│   ├── schema.md           ← DB 스키마 (현재 + 추가 예정)
│   ├── grading_sources.md  ← 어휘 등급 목록 조사와 결정
│   └── idiom_detection.md  ← 불연속 숙어 탐지 설계와 평가 결과
├── en-en/
│   ├── scripts/
│   │   ├── build_dict_db.py          kaikki JSONL → dict.db
│   │   ├── build_levels.py           dict.db + word_levels (CEFR, 교육과정)
│   │   ├── build_idioms.py           dict.db + 숙어 표 (kaikki에서 직접, 탐지 패턴 포함)
│   │   ├── eval_idioms.py            숙어 탐지기 평가 (kaikki 예문이 정답)
│   │   ├── parse_kr_curriculum.py    교육과정 PDF → CSV
│   │   ├── dict.py                   CLI 조회
│   │   ├── extract_pronunciations.py 품사별 미국식 발음 선택 (개선된 로직)
│   │   └── cefr_grading.py           CEFR-J + Octanove 등급 판정
│   ├── app/                          Fly.io 웹앱 (server.py, idiom_detect.py, static/index.html, static/test.html)
│   ├── data/raw/                     kaikki-en.jsonl (3.1GB), english_idioms.json (옛 숙어 목록, 비교용)
│   ├── data/cefr/                    CEFR-J 1.5, Octanove 1.0 CSV + 라이선스 메모
│   ├── data/kr_curriculum/           교육과정 기본 어휘 CSV
│   └── data/build/                   dict.db(.gz), pronunciations_en.json
├── en-ko/  scripts/ + data/
├── zh-en/  data/
├── ko-ko/  data/
├── shared/ scripts/ + data/
└── en-zh/ ko-en/ ko-zh/ zh-ko/ zh-zh/   (아직 README만)
```

용량이 큰 파일(`kaikki-en.jsonl`, `dict.db`, `dict.db.gz`)은 git에 넣지 않는다. 원본은 `python3 fetch_data.py`로 받고, DB는 빌드해서 만든다.

---

## 시작하기

### 이 Mac에서

환경(`.venv`), 원본(`kaikki-en.jsonl`), 빌드된 `dict.db`가 이미 다 있다. 바로 쓰면 된다.

```bash
cd ~/marginalia-dictionary

# 영영사전 조회 (CLI)
.venv/bin/python en-en/scripts/dict.py object
.venv/bin/python en-en/scripts/build_levels.py --check went colour object

# 데이터 확인 페이지 → http://localhost:8080/test  (끌 때 Ctrl+C)
cd en-en/app && ../../.venv/bin/python server.py
```

### 새 컴퓨터에서 (처음 한 번)

```bash
git clone https://github.com/l1ll2lll3/marginalia-dictionary.git ~/marginalia-dictionary && cd ~/marginalia-dictionary
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python fetch_data.py                       # 원본 받기 (3.3GB, 끊기면 이어받음)
.venv/bin/python en-en/scripts/build_dict_db.py      # dict.db (~45초)
.venv/bin/python en-en/scripts/build_levels.py       # 등급 (~10초)
.venv/bin/python en-en/scripts/build_idioms.py       # 숙어 (~25초)
```

### 다시 빌드할 때

발음 선택 로직이나 원본을 바꿨으면 `build_dict_db.py` → `build_levels.py` → `build_idioms.py` 순서로 다시 돌린다 (`build_dict_db.py`가 표를 지우고 새로 만들기 때문에 등급과 숙어도 사라진다). 숙어만 바꿨으면 `build_idioms.py`만 돌리면 된다.

배포는 `en-en/README.md`를 볼 것 — **배포 전에 운영 DB의 user_examples 백업 필수.**

---

## 지금까지 논의한 것 (2026-10-17)

자세한 내용은 `docs/grading_sources.md`에 있다.

1. **책 데이터의 원래 "CEFR"은 단어 빈도에 CEFR 이름만 붙인 것이었다.** 달과 6펜스는 2026-09-28에 CEFR-J + Octanove로 다시 매겼다.
2. **CEFR-J + Octanove**는 단어 + 품사마다 CEFR 등급이 붙은 공개 목록이다 (A1~B2 7,798개, C1~C2 2,136개). 합쳐서 약 1만 쌍이라 문학 어휘의 36%는 목록에 없다.
3. **영어에는 HSK 같은 공식 단일 목록이 없다.** CEFR은 단어 목록이 없는 능력 기술이다. 가장 가까운 것은 Cambridge EVP인데 통째로 쓰기 어렵다. Oxford 5000, Pearson GSE, NGSL도 검토했다.
4. **한국 교육과정 기본어휘(2022 개정)** 3,000단어군에는 초등(`*`) / 중고 공통(`**`) / 고교 선택 표시가 있다. 정부 고시라 저작권 걱정이 없다. 고등학교 위로는 "교육과정 밖" 하나로 묶는다.
5. **사전 DB에 단어마다 등급을 넣는다.** 단, 이 규칙을 따른다:
   - 목록에 있는 단어 + 품사에만 넣고, 나머지는 비운다. 빈도로 추정하는 건 책 파이프라인이 한다.
   - 철자 변형·굴절형은 원형 등급을 물려받고, 출처를 `inherited`로 적는다.
   - CEFR과 한국 교육과정 두 체계를 같이 둔다. 별도 표 `word_levels`로 만든다 (`docs/schema.md`).
   - 사전 등급은 기본값이고, 책에서 덮어쓸 수 있다.
6. **운영 사전에도 품사별 발음 버그가 있다.** `object` 동사에 명사 발음이 들어가 있다. 달과 6펜스에서 고친 선택 로직(`extract_pronunciations.py`)을 사전 빌드에도 쓴다.

---

## 다음 작업

완료 (2026-10-17): 개선된 발음 선택을 사전 전체에 적용(`pronunciations`), 등급 표 `word_levels`(CEFR + 교육과정, 굴절형·철자 이형 상속), 교육과정 PDF 파싱, 데이터 확인 페이지(`/test`).

1. **배포 전에** 운영 DB의 `user_examples`를 백업하고 옮긴다 (`docs/schema.md`의 배포 함정 참고). 그다음 새 dict.db를 Fly에 올린다.
2. 교육과정의 접사 파생형(un-, -ness … 36개)을 단어군으로 펼친다. 단순 접사 떼기는 오탐이 많아서 Wiktionary 어원(affix 템플릿)을 쓰는 방법을 검토한다.
3. reading 리포의 `regrade_vocabulary.py`·`extract_pronunciations.py`가 이 사전(`word_levels`, `pronunciations`)을 읽도록 바꾼다. reading 쪽 작업이다.
4. **`shared/data/multilingual_dict.json`을 대체한다** (2026-10-17 결정). 6개 언어쌍 29MB인데 품질이 낮다. 역방향으로 뒤집은 데이터라 en_ko 키에 영어 뜻풀이 문장이 섞여 있고("integration, combination"), 한중·중한은 뜻이 엉킨다(酉 → 完全, 犬 → 개 같은 놈).
   - dict.db에 `translations` 표를 만든다: kaikki-en(이미 있음)의 뜻별 `translations`에서 en→ko, en→zh를 뽑는다. 뜻(sense)이 같이 붙어 있어서 문맥에 맞는 번역을 고를 수 있다. 예: acquaintance (person) → ko 아는 사람·지인 / zh 熟人·相識.
   - `merge_en_ko_dict.py`가 JSON 대신 이 표를 쓰게 바꾼다.
   - ko·zh가 표제어인 쪽(ko-en, zh-en, ko-zh, zh-ko)은 KRDICT와 CC-CEDICT로 만든다.
   - 다 되면 JSON을 리포에서 뺀다. reading 쪽에서 이 JSON을 쓰는 `api_server.py`(`/api/dictionary/lookup`)와 `add_vocab_translations.py`는 reading 세션에서 새 표로 바꾼다.
5. 한국어 사전 파이프라인을 만든다 (KRDICT, ko-ko / ko-en). KRDICT 등급(초급·중급·고급)도 `word_levels`에 `scheme='krdict'`로 넣는다.
6. 문장 속 불연속 숙어 탐지 (take *the cost* into account). 설계는 `docs/idiom_detection.md`에 있다 (2026-11-07). 탐지기(`en-en/app/idiom_detect.py`)와 API(`POST /api/idioms/detect`)까지 만들었다 (불연속 재현율 80.2%, v2는 47.7%). 사전 검색의 숙어 후보도 만들었다. 정밀도는 약 77%(다른 책 200개 표본). 남은 것: 소유격 + 신체 표현 오탐 처리, 운영 배포.

## 라이선스

**코드**는 MIT 라이선스다 (`LICENSE`). **데이터**(`*/data/`)는 원래 출처의 라이선스를 따른다. 특히 CC BY-SA 데이터로 만든 산출물(dict.db 등)을 배포하면 같은 조건이 적용된다.

| 데이터 | 라이선스 |
|---|---|
| Wiktionary (kaikki.org, wiktextract) | CC BY-SA 3.0 / 4.0 |
| CC-CEDICT | CC BY-SA 4.0 |
| CEFR-J Wordlist 1.5 | 연구·상업 이용 무료, 출처 표기 |
| Octanove Vocabulary Profile 1.0 | CC BY-SA 4.0 |
| 2022 개정 교육과정 기본 어휘 | 정부 고시 (저작권법 제7조, 보호받지 않는 저작물) |
