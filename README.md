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
├── docs/
│   ├── schema.md           ← DB 스키마 (현재 + 추가 예정)
│   └── grading_sources.md  ← 어휘 등급 목록 조사와 결정
├── en-en/
│   ├── scripts/
│   │   ├── build_dict_db.py          kaikki JSONL → dict.db
│   │   ├── dict.py                   CLI 조회
│   │   ├── extract_pronunciations.py 품사별 미국식 발음 선택 (개선된 로직)
│   │   └── cefr_grading.py           CEFR-J + Octanove 등급 판정
│   ├── app/                          Fly.io 웹앱 (server.py, static/, Dockerfile, fly.toml)
│   ├── data/raw/                     kaikki-en.jsonl (3.1GB), english_idioms.json
│   ├── data/cefr/                    CEFR-J 1.5, Octanove 1.0 CSV + 라이선스 메모
│   └── data/build/                   dict.db(.gz), pronunciations_en.json
├── en-ko/  scripts/ + data/
├── zh-en/  data/
├── ko-ko/  data/
├── shared/ scripts/ + data/
└── en-zh/ ko-en/ ko-zh/ zh-ko/ zh-zh/   (아직 README만)
```

용량이 큰 파일(`kaikki-en.jsonl`, `dict.db`, `dict.db.gz`)은 git에 넣지 않는다. 다른 컴퓨터에서 작업할 때 받는 방법은 `en-en/README.md`에 있다.

---

## 시작하기

```bash
cd ~/marginalia-dictionary
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

# 영영사전 조회
.venv/bin/python en-en/scripts/dict.py object
.venv/bin/python en-en/scripts/dict.py "a piece of cake"

# dict.db 다시 빌드 (~3분)
.venv/bin/python en-en/scripts/build_dict_db.py
```

웹앱 로컬 실행과 배포는 `en-en/README.md`를 볼 것.

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

1. `build_dict_db.py`에 `extract_pronunciations._pick_ipa()`를 적용하고, 새 덤프로 다시 빌드한다.
2. `word_levels` 표를 만들고 CEFR-J + Octanove를 넣는다. 철자 변형·굴절형 상속도 포함한다.
3. 교육과정 기본어휘 PDF를 파싱한다. 3,000단어군 → `kr_curriculum_2022`.
4. **배포 전에** 운영 DB의 `user_examples`를 백업하고 옮긴다 (`docs/schema.md`의 배포 함정 참고).
5. reading 리포의 `regrade_vocabulary.py`가 `word_levels`를 읽도록 바꾼다. 이 작업은 reading 쪽에서 한다.
6. 한국어 사전 파이프라인을 만든다 (KRDICT, ko-ko / ko-en).

## 라이선스

| 데이터 | 라이선스 |
|---|---|
| Wiktionary (kaikki.org, wiktextract) | CC BY-SA 3.0 / 4.0 |
| CC-CEDICT | CC BY-SA 4.0 |
| CEFR-J Wordlist 1.5 | 연구·상업 이용 무료, 출처 표기 |
| Octanove Vocabulary Profile 1.0 | CC BY-SA 4.0 |
| 2022 개정 교육과정 기본 어휘 | 정부 고시 (저작권법 제7조, 보호받지 않는 저작물) |
