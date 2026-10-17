# DB 스키마

## 1. en-en: `en-en/data/build/dict.db` (현재)

Marginalia Dictionary(https://marginalia-dict.fly.dev/)가 쓰는 SQLite DB다. `en-en/scripts/build_dict_db.py`가 kaikki Wiktionary JSONL에서 만든다.
- 압축본 `dict.db.gz`는 142MB, 풀면 319MB다.
- 마지막 빌드는 2026-04, 2.5GB 덤프 기준이다. `data/raw/kaikki-en.jsonl`(3.1GB, 2026-09 다운로드)로 다시 빌드하면 숫자가 바뀐다.

### words — 표제어 × 품사 × 어원 항목

```sql
CREATE TABLE words (
    id              INTEGER PRIMARY KEY,
    word            TEXT NOT NULL,   -- 원래 표기 (mediævalism)
    word_normalized TEXT NOT NULL,   -- 소문자 + 고어 문자 정규화 (æ→ae, œ→oe, é→e …)
    pos             TEXT,            -- kaikki 품사: noun, verb, adj, adv, name, phrase …
    ipa             TEXT,            -- 발음 1개. "US 우선, 없으면 첫 번째" (아래 '알려진 문제' 참고)
    etymology       TEXT             -- 어원, 300자에서 자름
);
CREATE INDEX idx_words_normalized ON words(word_normalized);
CREATE INDEX idx_words_word ON words(word);
```

| 항목 | 값 |
|---|---|
| 행 | 1,403,717 |
| 서로 다른 word | 1,309,296 |
| (word, pos)가 겹치는 경우 | 13,125쌍. Wiktionary가 어원별로 항목을 나눠서 그렇다 (refuse: noun 2행) |
| ipa 있음 | 126,882 (9%) |
| etymology 있음 | 506,035 |
| pos 상위 | noun 788K · verb 210K · adj 179K · name 178K · adv 27K |

**행 하나 = kaikki JSONL 한 줄.** 그래서 (word, pos)는 유일하지 않다. 등급이나 발음을 (word, pos)에 붙일 때는 이 점에 주의해야 한다.

### senses — 뜻

```sql
CREATE TABLE senses (
    id        INTEGER PRIMARY KEY,
    word_id   INTEGER NOT NULL REFERENCES words(id),
    sense_num INTEGER NOT NULL,      -- 1부터
    gloss     TEXT NOT NULL,         -- 영어 풀이
    example   TEXT                   -- 예문 1개 (짧은 것 우선)
);
CREATE INDEX idx_senses_word_id ON senses(word_id);
```
1,677,158행, 예문이 있는 행은 335,593.

### idioms — 숙어

```sql
CREATE TABLE idioms (
    id                INTEGER PRIMARY KEY,
    phrase            TEXT NOT NULL,
    phrase_normalized TEXT NOT NULL,
    meaning           TEXT
);
CREATE INDEX idx_idioms_normalized ON idioms(phrase_normalized);
```
69,651행. 원본은 `data/raw/english_idioms.json`(wiktextract 추출)이다.

### user_examples — 사용자 예문 (운영 DB에만 있음)

`app/server.py`의 `init_examples_table()`이 **Fly 볼륨의 `/data/dict.db`에** 만든다. 배포하는 `dict.db.gz`에는 없다.

```sql
CREATE TABLE user_examples (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    lemma        TEXT NOT NULL,
    surface      TEXT,
    sentence     TEXT NOT NULL,
    cefr         TEXT,
    source_type  TEXT DEFAULT 'manual',
    source_label TEXT,
    trigger      TEXT DEFAULT 'manual',
    anon_token   TEXT,
    status       TEXT DEFAULT 'approved',
    score        INTEGER DEFAULT 0,
    flags        INTEGER DEFAULT 0,
    created_at   TEXT DEFAULT (datetime('now'))
);
CREATE INDEX idx_ue_lemma ON user_examples (lemma, status, score DESC);
```

> ⚠️ **배포 함정**: `app/start.sh`는 `dict.db.gz`가 볼륨의 `dict.db`보다 새것이면 **볼륨 DB를 통째로 덮어쓴다.** 그러면 그동안 쌓인 `user_examples`가 사라진다. DB를 다시 빌드해서 배포하기 전에 운영 DB의 `user_examples`를 먼저 백업하고 옮길 것. 아니면 user_examples를 별도 DB 파일로 분리할 것.

### 알려진 문제

- **품사별 발음이 틀린 경우가 있다.** `object|verb`의 ipa가 명사 발음 `/ˈɑb.d͡ʒɛkt/`이다. 빌드 스크립트가 "US 태그 우선, 없으면 첫 번째"로만 고르기 때문이다. 품사·강세·영국식 기호·축약형까지 따지는 개선된 선택 로직은 `scripts/extract_pronunciations.py`의 `_pick_ipa()`에 있다 (2026-09-28, reading 리포의 버그 리포트 1~3번을 반영). 이 로직을 `build_dict_db.py`에 옮기는 것이 다음 작업이다.
- 발음 기호에 파찰음 tie bar(`d͡ʒ`)가 남아 있다. reading 쪽 산출물에서는 없앴다 (`912855d`).

---

## 2. 추가 예정: 등급 (`word_levels`)

결정 배경은 `docs/grading_sources.md` §5에 있다. 등급 체계가 여러 개(CEFR, 한국 교육과정, 앞으로 KRDICT·HSK)라서 `words`에 칸을 계속 추가하지 않고 별도 표로 둔다.

```sql
CREATE TABLE word_levels (
    word_normalized TEXT NOT NULL,
    pos             TEXT NOT NULL,   -- kaikki 품사. 목록에 품사가 없으면 '*'
    scheme          TEXT NOT NULL,   -- 'cefr' | 'kr_curriculum_2022' | (나중에) 'krdict' | 'hsk3'
    level           TEXT NOT NULL,   -- cefr: A1~C2 / kr_curriculum_2022: elementary | middle_common | high_elective
    source          TEXT NOT NULL,   -- 'cefr-j' | 'octanove' | 'moe-2022' | 'inherited'
    inherited_from  TEXT,            -- source='inherited'일 때 원형 (colour → color)
    PRIMARY KEY (word_normalized, pos, scheme)
);
CREATE INDEX idx_levels_word ON word_levels(word_normalized);
```

규칙:
- **목록에 있는 것만 넣는다.** 행이 없으면 "목록에 없음"이다. 빈도로 추정한 값은 넣지 않는다.
- 한 (word, pos, scheme)에 여러 값이 겹치면 낮은 등급을 남긴다 (학습자가 처음 만나는 수준이 그 단어의 문턱).
- 교육과정 목록은 단어군 단위다. 굴절형과 36개 접사 파생형은 `inherited`로 펼친다. 단, 의존 어근 파생(precious)은 제외한다.
- 교육과정 목록에 없는 단어는 "교육과정 밖"이다. 이것도 행을 만들지 않고, 행이 없는 것으로 표현한다.
- 등급은 (word, pos)에 붙인다. 같은 (word, pos)에 어원 항목이 여러 개여도 등급은 하나다.

## 3. 추가 예정: 품사별 발음 (`pronunciations`)

```sql
CREATE TABLE pronunciations (
    word_normalized TEXT NOT NULL,
    pos             TEXT NOT NULL,
    ipa             TEXT NOT NULL,   -- 음소 표기 /…/ 만
    variety         TEXT,            -- 'US' | 'unknown' | 'UK' …
    variant_of      TEXT,            -- 철자 변형이라 원형 발음을 가져온 경우 (colour → color)
    PRIMARY KEY (word_normalized, pos)
);
```

`scripts/extract_pronunciations.py`의 캐시 `data/build/pronunciations_en.json`(7,736쌍, 키 `lemma|POS`)이 이 표의 일부다. 지금은 Marginalia 책 표제어만 담겨 있다. 사전 전체로 넓히려면 `--book` 대신 kaikki 전체를 대상으로 돌리게 바꿔야 한다.

---

## 4. 다른 언어쌍 데이터 (현재 JSON)

| 파일 | 형식 | 규모 |
|---|---|---|
| `en-ko/data/en_ko_dict.json` | `{ "dictionary": {"ko": ["사전", "자서", …], "src": "kaikki"} }` — `merge_en_ko_dict.py` 합본 (src: kaikki / multilingual_dict / Claude 캐시) | 20,286 |
| `shared/data/multilingual_dict.json` | 6쌍 묶음 + `metadata`, `stats` | en_ko 35,689 · en_zh 129,551 · ko_en 45,112 · zh_en 168,057 · ko_zh 15,473 · zh_ko 45,020 |
| `zh-en/data/cedict_ts.txt.gz` | CC-CEDICT 원본: `繁體 简体 [pin1 yin1] /뜻/뜻/` | 124,380 항목 |
| `ko-ko/data/ko-extract.jsonl.gz` | 한국어 Wiktionary wiktextract 추출 (JSONL) | 355,243 항목 |

이 데이터들도 언어쌍마다 SQLite로 옮길 때는 en-en과 같은 구조(`words` / `senses` / `word_levels` / `pronunciations`)를 쓰는 걸 기본으로 한다. 그래야 앱과 API가 언어쌍과 상관없이 같은 질의를 쓸 수 있다.
