# DB 스키마

## 1. en-en: `en-en/data/build/dict.db`

Marginalia Dictionary(https://marginalia-dict.fly.dev/)가 쓰는 SQLite DB다. 아래 순서로 만든다.

```bash
.venv/bin/python en-en/scripts/build_dict_db.py        # words, senses, word_links, pronunciations (~45초)
.venv/bin/python en-en/scripts/parse_kr_curriculum.py  # 교육과정 PDF → CSV (CSV는 git에 있으니 보통 생략)
.venv/bin/python en-en/scripts/build_levels.py         # word_levels (~10초)
.venv/bin/python en-en/scripts/build_idioms.py         # idioms, idiom_senses, idiom_examples, idiom_forms, idiom_patterns (~25초)
```

- 2026-10-17 빌드 기준이다 (`kaikki-en.jsonl` 2026-09 덤프). 크기 430MB.
- 운영 서버(Fly)에는 아직 2026-04 빌드(319MB, 등급·품사별 발음 없음)가 올라가 있다. 배포 전에 아래 user_examples 함정을 볼 것.
- 이전 빌드는 비교용으로 `dict.pre-rebuild.db`에 남겨뒀다 (gitignore).

### words — 표제어 × 품사 × 어원 항목

```sql
CREATE TABLE words (
    id              INTEGER PRIMARY KEY,
    word            TEXT NOT NULL,   -- 원래 표기 (mediævalism)
    word_normalized TEXT NOT NULL,   -- 소문자 + 고어 문자 정규화 (æ→ae, œ→oe, é→e …)
    pos             TEXT,            -- kaikki 품사: noun, verb, adj, adv, name, phrase …
    ipa             TEXT,            -- 이 어원 항목의 발음. extract_pronunciations._pick_ipa()로 고름
    ipa_variety     TEXT,            -- us | uk | unknown | dialect
    etymology       TEXT             -- 어원, 300자에서 자름
);
CREATE INDEX idx_words_normalized ON words(word_normalized);
CREATE INDEX idx_words_word ON words(word);
```

| 항목 | 값 |
|---|---|
| 행 | 1,492,836 |
| 서로 다른 word | 1,390,507 |
| (word_normalized, pos)가 겹치는 경우 | 32,903쌍. 어원별 항목 분리(refuse: noun 2행)와 대소문자 차이(Polish/polish) |
| ipa 있음 | 139,263 |
| etymology 있음 | 535,573 |
| pos 상위 | noun 832K · verb 222K · name 201K · adj 186K · adv 28K |

**행 하나 = kaikki JSONL 한 줄.** 그래서 (word, pos)는 유일하지 않다. 그래서 (단어, 품사) 단위 값은 `pronunciations`와 `word_levels`에 따로 둔다.

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
1,785,991행, 예문이 있는 행은 363,415.

### word_links — 원형 연결

```sql
CREATE TABLE word_links (
    word_id INTEGER NOT NULL REFERENCES words(id),
    target  TEXT NOT NULL,   -- 원형 (원래 표기)
    kind    TEXT NOT NULL,   -- form_of | alt_of | spelling
    tags    TEXT             -- 첫 뜻의 태그, 공백 구분 ("form-of past", "alt-of archaic" …)
);
CREATE INDEX idx_links_word ON word_links(word_id);
```

| kind | 출처 | 행 | 예 |
|---|---|---|---|
| `form_of` | 첫 뜻의 구조화 필드 `form_of` | 535,688 | went → go, children → child |
| `alt_of` | 첫 뜻의 구조화 필드 `alt_of` | 151,602 | craftman → craftsman |
| `spelling` | `_variant_target()`: 뜻풀이의 "… spelling of X" 등. 굴절형·약어는 제외 | 119,153 | colour → color |

등급 상속(`build_levels.py`)과 철자 변형의 발음 채우기(`pronunciations.variant_of`)에 쓴다. **첫 뜻만** 본다. 첫 뜻이 고유한 의미인 항목(found = 설립하다)이 다른 뜻 때문에 원형을 물려받지 않게 하려는 것이다.

### idioms — 숙어 (2026-11-07부터 `build_idioms.py`)

kaikki-en의 여러 단어 원형 항목에서 직접 뽑는다. 무엇을 숙어로 넣는지는 `docs/idiom_detection.md` §4.1에 있다. 예전에는 reading에서 만든 `english_idioms.json`(69,651행, 선정 기준 불명, 첫 뜻만)을 넣었다. 이 파일은 지금 `build_idioms.py --compare`의 비교용으로만 남아 있다.

```sql
CREATE TABLE idioms (                -- 33,823행. 숙어 하나 = kaikki 원형 항목 하나
    id                INTEGER PRIMARY KEY,
    phrase            TEXT NOT NULL,
    phrase_normalized TEXT NOT NULL,
    meaning           TEXT,          -- 첫 숙어 뜻. 문자 그대로의 뜻("Used other than figuratively")은 건너뛴다
    pos               TEXT,
    included_by       TEXT           -- 숙어로 넣은 이유: idiomatic, phrasal, pos:verb, figuratively …
);
CREATE TABLE idiom_senses (          -- 49,544행. 뜻 전부
    idiom_id  INTEGER NOT NULL REFERENCES idioms(id),
    sense_idx INTEGER NOT NULL,
    gloss     TEXT NOT NULL,
    tags      TEXT,                  -- JSON 배열: ["idiomatic", "transitive"]
    literal   INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE idiom_examples (        -- 61,092행. 뜻별 예문. "Synonyms:" 같은 줄은 뺀다
    idiom_id  INTEGER NOT NULL REFERENCES idioms(id),
    sense_idx INTEGER NOT NULL,
    text      TEXT NOT NULL,
    type      TEXT                   -- example | quotation
);
CREATE TABLE idiom_forms (           -- 74,210행. 활용형·이형 → 원형 (took into account, pull up one's socks)
    idiom_id        INTEGER NOT NULL REFERENCES idioms(id),
    form            TEXT NOT NULL,
    form_normalized TEXT NOT NULL,
    kind            TEXT NOT NULL,   -- form (활용형) | alt (이형)
    tags            TEXT
);
CREATE TABLE idiom_patterns (        -- 38,453행. 탐지용. 원형과 이형마다 하나
    idiom_id INTEGER NOT NULL REFERENCES idioms(id),
    source   TEXT NOT NULL,          -- 패턴을 만든 표제
    pattern  TEXT NOT NULL,          -- JSON 배열. 아래 참고
    anchor   TEXT NOT NULL,          -- 가장 드문 고정 단어 (후보 찾기 열쇠)
    n_fixed  INTEGER NOT NULL        -- 고정 단어 수
);
```

`pattern`의 원소 (`docs/idiom_detection.md` §4.2):

| t | 뜻 | 예 |
|---|---|---|
| `HEAD` | 활용하는 동사. `lemma`, `forms`(활용형) | take → took, taken |
| `LIT` | 고정 단어 `w` | into, account |
| `POSS` | one's / someone's | make up **his** mind |
| `NP` | someone / something | |
| `REFL` | oneself | |
| `OBJ` | 동사 바로 뒤 목적어 자리 (`opt`) | take **the cost** into account |

```
take into account   → take [OBJ?] into account
make up one's mind  → make up [POSS] mind
keep an eye on      → keep an eye on
```

확인: `.venv/bin/python en-en/scripts/build_idioms.py --check "take into account" "look up"`

`/api/idiom`은 `idioms`에서 못 찾으면 `idiom_forms`에서 찾는다 (took into account → take into account).

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

- 발음 기호에 파찰음 tie bar(`d͡ʒ`)가 남아 있다. 원본 그대로 두고, 표시할 때 정리한다 (reading 쪽 산출물에서는 없앴다, `912855d`).
- 발음 선택은 휴리스틱이라 남은 오류가 있다. 원본에 미국식 표준형이 아예 없으면 영국식이나 지역 발음이 뽑힌다 (onto → /ˈɒn.tuː/는 미국식이 전부 Northern-US·Midland 태그라 RP가 선택됨). 등급이 있는 단어 14,443쌍 중 영국식 기호 비율은 1.3%다.

---

## 2. 등급 (`word_levels`)

결정 배경은 `docs/grading_sources.md` §5에 있다. 등급 체계가 여러 개(CEFR, 한국 교육과정, 앞으로 KRDICT·HSK)라서 `words`에 칸을 계속 추가하지 않고 별도 표로 둔다. `en-en/scripts/build_levels.py`가 만든다.

```sql
CREATE TABLE word_levels (
    word_normalized TEXT NOT NULL,
    pos             TEXT NOT NULL,   -- kaikki 품사. 목록에 품사가 없으면 '*'
    scheme          TEXT NOT NULL,   -- 'cefr' | 'kr_curriculum_2022' | (나중에) 'krdict' | 'hsk3'
    level           TEXT NOT NULL,   -- cefr: A1~C2 / kr_curriculum_2022: elementary | middle_common | high_elective
    source          TEXT NOT NULL,   -- 'cefr-j' | 'octanove' | 'moe-2022' | 'inherited'
    inherited_from  TEXT,            -- inherited: 원형 (went → go) / moe-2022: 단어군 대표형 (colour → color)
    PRIMARY KEY (word_normalized, pos, scheme)
);
CREATE INDEX idx_levels_word ON word_levels(word_normalized);
```

| scheme | 목록 | 상속 | 분포 |
|---|---|---|---|
| `cefr` | 9,912 | 12,433 | A1 2,656 · A2 3,167 · B1 5,665 · B2 6,538 · C1 2,314 · C2 2,005 |
| `kr_curriculum_2022` | 3,283 | 9,110 | elementary 3,559 · middle_common 4,935 · high_elective 3,899 |

규칙:
- **목록에 있는 것만 넣는다.** 행이 없으면 "목록에 없음"이다. 빈도로 추정한 값은 넣지 않는다.
- 한 (word, pos, scheme)에 여러 값이 겹치면 낮은 등급을 남긴다 (학습자가 처음 만나는 수준이 그 단어의 문턱).
- **cefr**: 목록의 (단어, 품사)를 kaikki 품사로 옮겨 넣는다 (`adjective`→`adj`, `modal auxiliary`→`verb`, `determiner`→`det`·`article` …). 사전에 같은 (단어, 품사)가 없는 목록 항목 114개는 넣지 않았다 (대부분 `a few` 같은 여러 단어 한정사).
- **kr_curriculum_2022**: 품사 구분이 없어 `pos='*'`. 원문의 대표형·철자 이형·괄호 속 파생형을 `en-en/data/kr_curriculum/moe_2022_basic_vocab.csv`(3,283행)로 뽑아 넣는다. 지침은 800/1,200/1,000개라고 하는데, 실제로 세면 초등이 801개다 (중복·파싱 오류가 없는 것은 확인함).
- **상속**: 그 (단어, 품사)의 첫 항목이 `word_links`로 원형을 가리키고, 첫 뜻의 태그가 전부 굴절·표준 이형 태그(`INHERIT_OK_TAGS`)일 때만 원형의 등급을 가져온다. 그래서 shew(고어), temperment(오용), ur(인터넷) 같은 것은 물려받지 않는다. 원형도 목록에서 직접 온 등급이어야 한다 (상속의 상속은 하지 않음).
- **아직 안 한 것**: 교육과정 지침의 "36개 접사 파생형"(un-, -ness …)은 펼치지 않았다. kindness를 kind의 단어군으로 넣으려면 접사 분석이 필요한데, 단순 접사 떼기는 오탐이 많다(uncle ≠ un + cle).
- 고유명사 항목(`pos='name'`)에는 서버가 `'*'` 등급을 붙이지 않는다 (Went 강 ≠ went).

## 3. 품사별 발음 (`pronunciations`)

```sql
CREATE TABLE pronunciations (
    word_normalized TEXT NOT NULL,
    pos             TEXT NOT NULL,
    ipa             TEXT NOT NULL,   -- 음소 표기 /…/ 만
    variety         TEXT,            -- us | uk | unknown | dialect
    variant_of      TEXT,            -- 철자 변형이라 원형 발음을 가져온 경우 (colour → color)
    PRIMARY KEY (word_normalized, pos)
);
```

- (단어, 품사)마다 Wiktionary 순서상 첫 항목(주된 뜻)의 발음을 쓴다. 대소문자만 다른 항목이 있으면 소문자 쪽을 먼저 본다.
- 직접 129,226쌍 + 철자 변형에서 가져온 것 42,577쌍 = 171,803쌍.
- 이전 빌드 대비 영국식 기호(ɒ·əʊ·ɜː) 비율이 14.4% → 6.9%다. 등급이 있는 단어만 보면 1.3%다.
- variety 분포: unknown 82,161 · us 75,110 · uk 12,948 · dialect 1,584. dialect는 표준형 후보가 아예 없는 단어다.
- 선택 로직은 `en-en/scripts/extract_pronunciations.py`의 `_pick_ipa()`에 있다. 2026-10-17에 사전 전체에 적용하면서 고친 것:
  - 지역 방언 판정을 허용 목록 방식으로 바꿈 (fall /faːl/, fish /fɘʃ/ 방지)
  - note 칸 해석: 지역명이 있으면 방언, US/RP 표기, 축약(flapping)
  - 구별 부호와 j만 다른 것은 축약형으로 보지 않음 (fish, student /ˈstu.dn̩t/)
  - tr 파찰음화 (interesting /ˈɪnt͡ʃɹ…/)
  - 표준 태그가 있을 때 태그 없는 부차 변형 감점 (thank /ðæŋk/)
  - British Southern Standard(새 영국식 표기)를 전통 RP 뒤에 둠
- reading 리포의 `gutenberg/extract_pronunciations.py`는 이 수정 전 버전이다. 책 데이터에 다시 적용하려면 이쪽 로직을 쓴다.

---

## 4. 다른 언어쌍 데이터 (현재 JSON)

| 파일 | 형식 | 규모 |
|---|---|---|
| `en-ko/data/en_ko_dict.json` | `{ "dictionary": {"ko": ["사전", "자서", …], "src": "kaikki"} }` — `merge_en_ko_dict.py` 합본 (src: kaikki / multilingual_dict / Claude 캐시) | 20,286 |
| `shared/data/multilingual_dict.json` | 6쌍 묶음 + `metadata`, `stats` | en_ko 35,689 · en_zh 129,551 · ko_en 45,112 · zh_en 168,057 · ko_zh 15,473 · zh_ko 45,020 |
| `zh-en/data/cedict_ts.txt.gz` | CC-CEDICT 원본: `繁體 简体 [pin1 yin1] /뜻/뜻/` | 124,380 항목 |
| `ko-ko/data/ko-extract.jsonl.gz` | 한국어 Wiktionary wiktextract 추출 (JSONL) | 355,243 항목 |

이 데이터들도 언어쌍마다 SQLite로 옮길 때는 en-en과 같은 구조(`words` / `senses` / `word_levels` / `pronunciations`)를 쓰는 걸 기본으로 한다. 그래야 앱과 API가 언어쌍과 상관없이 같은 질의를 쓸 수 있다.
