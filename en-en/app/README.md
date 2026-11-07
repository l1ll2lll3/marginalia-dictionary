# Marginalia Dictionary

Wiktionary 기반 영어 사전 웹앱. 1.4M 단어 + 70K 숙어, SQLite, Fly.io 배포.

**Live**: https://marginalia-dict.fly.dev/

---

## 사전 데이터 구축 과정

### 1. 원본 데이터

| 소스 | 항목 수 | 라이선스 |
|------|---------|----------|
| [kaikki.org](https://kaikki.org/dictionary/English/) Wiktionary JSONL | 1,403,717 단어 | CC BY-SA 3.0 |
| 숙어 (같은 kaikki에서 `build_idioms.py`가 뽑음) | 33,823 숙어 + 활용형·이형 74,210 | CC BY-SA 3.0 |

- `kaikki.org-dictionary-English.jsonl` (2.5GB) — Wiktionary 전체 영어 사전 덤프
- 각 항목: word, pos, IPA, etymology, senses (gloss + example)

### 2. SQLite DB 빌드 (`build_dict_db.py`)

```bash
python build_dict_db.py          # ~3분, dict.db (315MB) 생성
python build_dict_db.py --stats  # 통계 확인
```

**3개 테이블**:

```sql
words (id, word, word_normalized, pos, ipa, etymology)
senses (id, word_id, sense_num, gloss, example)
idioms (id, phrase, phrase_normalized, meaning, pos, included_by)   -- build_idioms.py. 나머지 숙어 표는 docs/schema.md
```

- `word_normalized`: 고어 정규화 (ae→ae, oe→oe 등) — `mediaevalism` 검색 시 `mediævalism`도 매칭
- IPA: US 발음 우선, 없으면 첫 번째 발음
- Etymology: 300자 제한
- 뜻(sense)별 예문 1개 (짧은 것 우선)
- 배치 삽입 (10,000건씩) + 인덱스 3개

### 3. CLI 사전 (`dict.py`)

```bash
python dict.py bourdon            # 단어 조회 (IPA, 뜻, 예문, 어원)
python dict.py "a piece of cake"  # 숙어 (관사 자동 제거 fallback)
python dict.py --search "medi*"   # 와일드카드 검색
python dict.py draw --max 10      # 뜻 최대 10개
```

---

## 웹앱 구조

```
dict_app/
├── server.py              # Flask API 서버
├── static/index.html      # 웹 UI (단일 HTML, vanilla JS)
├── Dockerfile
├── fly.toml               # Fly.io 배포 설정
├── start.sh               # 시작 스크립트 (DB 압축 해제)
└── requirements.txt       # flask, gunicorn
```

### API 엔드포인트

| Method | Path | 설명 |
|--------|------|------|
| GET | `/api/lookup?word=bourdon` | 단어 조회 (IPA, 뜻, 어원) |
| GET | `/api/idiom?phrase=piece+of+cake` | 숙어 조회 (관사 제거 fallback) |
| GET | `/api/search?q=medi*` | 와일드카드 검색 |
| GET | `/` | 웹 UI |

### 웹 UI 기능

- 검색창 + 자동 모드 감지 (공백→숙어, *→검색, 그 외→단어)
- Word/Idiom/Search 탭 전환
- 단어: pos, IPA, 뜻(최대 8개), 예문, 어원
- 숙어: 관사 포함/미포함 모두 검색
- 매칭 실패 시 "Did you mean?" 제안
- 단어 검색에서 숙어 미발견 시 자동 fallback
- **팝업 사전**: 결과 텍스트 내 단어 선택(더블클릭/롱프레스) 시 팝업으로 뜻 표시
- WhatAP Browser Agent (pcode: 38129) RUM 모니터링

---

## 검색 기능 상세

### 1. 단어 검색 (Word)

단일 단어 입력 시 자동 선택. `word_normalized` 컬럼에서 정확히 일치하는 항목을 조회한다.

```
bourdon → noun (IPA, 뜻 8개, 예문, 어원)
saunter → noun + verb (POS별 별도 엔트리)
```

**고어(Archaic) 정규화**: 검색어와 DB 모두 정규화된 형태로 비교하여, 고어 철자로도 현대 철자로도 검색 가능하다.

| 고어 | 정규화 | 예시 |
|------|--------|------|
| æ → ae | mediævalism → mediaevalism | |
| œ → oe | manœuvre → manoeuvre | |
| ë → e | naïveté → naivete | |
| é, è → e | résumé → resume | |
| â, à → a | rôle → role | |

**Did you mean?**: 정확히 일치하는 단어가 없으면 접두사(prefix) 기반으로 최대 10개 제안.

```
saunt → Did you mean: saunter, sauntered, saunterer, ...?
```

**숙어 자동 fallback**: 단어 모드에서 결과도 제안도 없으면, 자동으로 숙어 검색을 시도한다.

### 2. 숙어 검색 (Idiom)

공백이 포함된 입력은 자동으로 숙어 모드. **3단계 fallback**으로 매칭률을 높인다:

```
[1단계] 정확 일치    "a piece of cake"  → a piece of cake ✅
[2단계] 관사 제거     "a piece of cake"  → piece of cake   (a/an/the 제거 후 재검색)
[3단계] 키워드 매칭   "take account"     → take into account, take account of, ...
[4단계] 부분 문자열   "piece"            → a piece of cake, piece of work, ...
```

**키워드 매칭 (불연속 숙어 검색)**:
- 입력 단어가 2개 이상일 때 활성화
- 각 단어를 AND 조건으로 조합하여, 모든 단어를 포함하는 숙어를 찾는다
- 단어 순서, 인접 여부 무관 — "take account" → "take **into** account" 매칭
- 최대 20개 반환 (LIMIT)

```
take account  → take into account, take account of, taken into account, ...  (6건)
give time     → give someone a hard time, give someone time, ...             (12건)
burn bridge   → burn one's bridges, burn that bridge when one comes to it    (10건)
```

**활용 시나리오**: 숙어의 정확한 형태를 모를 때 기억나는 핵심 단어 2~3개만 입력하면 된다.

### 3. 와일드카드 검색 (Search)

`*` 또는 `?`가 포함된 입력은 자동으로 검색 모드.

| 패턴 | 의미 | SQL 변환 |
|------|------|----------|
| `*` | 0개 이상의 임의 문자 | `%` |
| `?` | 정확히 1개의 임의 문자 | `_` |

```
medi*      → mediaeval, mediaevalism, medial, median, ...   (최대 30개)
*tion      → 모든 -tion 끝나는 단어
b??rd      → board, beard, ...
```

### 4. 팝업 사전 (Inline Lookup)

검색 결과 텍스트 안에서 모르는 단어를 바로 조회할 수 있다.

- **데스크톱**: 더블클릭으로 단어 선택 → 팝업 표시
- **모바일**: 롱프레스(길게 누르기)로 단어 선택 → 팝업 표시
- 팝업 내용: 단어, POS, IPA, 뜻 최대 3개
- **"Full entry →"** 클릭 시 메인 검색으로 전체 결과 이동
- 팝업 바깥 클릭/터치 시 자동 닫힘
- 영문 단어만 인식 (2~40자, 하이픈/아포스트로피 포함)

**동작 원리**: 선택된 텍스트를 `/api/lookup` API로 조회하여 결과를 선택 위치 근처에 툴팁으로 표시. 화면 아래 공간이 부족하면 위로 뒤집어 표시한다.

### 5. 자동 모드 감지

검색어 형태에 따라 자동으로 최적 모드를 선택한다. 수동 탭 전환도 가능.

| 입력 형태 | 자동 모드 | 이유 |
|-----------|-----------|------|
| `bourdon` | Word | 공백/와일드카드 없음 |
| `a piece of cake` | Idiom | 공백 포함 |
| `medi*` | Search | `*` 또는 `?` 포함 |

---

## Fly.io 배포

### 사전 조건

- [Fly CLI](https://fly.io/docs/flyctl/install/) 설치
- `fly auth login` 로그인

### 배포 순서

```bash
# 1. dict.db 빌드 (로컬)
cd gutenberg
python build_dict_db.py

# 2. DB 압축 → dict_app에 복사
gzip -k -c dict.db > dict_app/dict.db.gz    # 315MB → 142MB

# 3. Fly.io 앱 + 볼륨 생성 (최초 1회)
cd dict_app
fly apps create marginalia-dict --org personal
fly volumes create dict_data --region nrt --size 1 --yes

# 4. 배포
fly deploy                                    # Docker 빌드 + 업로드 (~2분)

# 5. 정리
rm dict.db.gz
```

### 인프라 구성

| 항목 | 값 |
|------|-----|
| 리전 | nrt (도쿄) |
| VM | shared-cpu-1x, 512MB RAM |
| Volume | 1GB persistent (dict.db 315MB) |
| auto-stop | 유휴 시 정지, 요청 시 자동 시작 |
| 비용 | $0 (무료 tier) |

### start.sh 동작

1. `/data/dict.db` 존재 확인
2. 없으면 이미지 내 `dict.db.gz` → `/data/dict.db`로 압축 해제 (최초 배포 시 1회)
3. gunicorn 시작 (workers=2)

### 재배포 (DB 변경 없을 때)

```bash
cd dict_app
fly deploy    # 코드만 변경, 볼륨의 dict.db는 유지
```

### 재배포 (DB 갱신)

```bash
# 기존 dict.db 삭제 후 재배포하면 start.sh가 새 gz에서 다시 추출
fly ssh console -a marginalia-dict -C "rm /data/dict.db"
fly deploy
```

---

## 라이선스

사전 데이터: [Wiktionary](https://en.wiktionary.org/) CC BY-SA 3.0
