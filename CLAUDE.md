# Marginalia Dictionary — Claude Code 컨텍스트

> 새 세션은 이 파일 → `README.md` → `docs/schema.md` → `docs/grading_sources.md` 순서로 읽고 시작할 것.

## 이 프로젝트는

Marginalia(문학으로 언어를 배우는 읽기 도구)에서 쓰는 다국어 사전을 만든다. 2026-10-17에 reading 리포(`~/reading`, 특히 `~/reading/gutenberg/`)에서 분리했다.

- **여기서 하는 일**: 사전 데이터 빌드, DB 스키마, 등급(CEFR·교육과정), 품사별 발음, 사전 웹앱·API
- **reading에서 하는 일**: 책 파이프라인 (`book_package.json`, 번역, EPUB/PDF, Flutter 앱). 이 사전을 가져다 쓴다.
- reading 쪽에 원본 스크립트가 아직 남아 있다 (복사해 왔고 옮기지 않았다). 사전을 고치는 작업은 이제 여기서 한다. 책에 적용하는 스크립트(`regrade_vocabulary.py`, `apply_pronunciations.py`, `audit_pronunciations.py`, `export_grade_review.py`, `enrich_vocabulary.py`, `sense_select.py`, `build_literary_dict.py`)는 책 데이터를 다루므로 reading에 남겨뒀다.

## 언어쌍 폴더

`표제어언어-풀이언어` 형식이다: `en-en` 영영, `en-ko` 영한, `ko-en` 한영, `en-zh` 영중, `zh-en` 중영, `zh-ko` 중한, `ko-zh` 한중, `ko-ko` 한한, `zh-zh` 중중. 지금 실제로 운영하는 건 **en-en**뿐이다.

## 사용자 선호 (reading 리포와 같다)

- 코딩보다 아이디어·사용성 검토가 먼저다. 문서화 먼저, 구현은 나중.
- **commit은 자유롭게, push는 사용자가 직접** 한다 (요청할 때만 push).
- 수동 데이터 입력은 절대 금지. 근거가 있는 목록이나 텍스트 분석으로만 만든다.
- 퍼블릭 도메인 / 오픈 라이선스 데이터만 쓴다.
- 커밋 메시지는 한국어로, 단위별로 자세히 쓴다.

## 지켜야 할 규칙

1. **등급은 목록에 실제로 있는 것만 사전에 넣는다.** 빈도 추정값은 넣지 않는다 (`docs/grading_sources.md` §5).
2. **배포 전에 `user_examples`를 백업한다.** `en-en/app/start.sh`는 새 `dict.db.gz`가 있으면 운영 볼륨의 DB를 덮어쓴다. 그러면 사용자가 기여한 예문이 사라진다.
3. **큰 파일은 커밋하지 않는다**: `kaikki-en.jsonl` (3.1GB), `dict.db` (319MB), `dict.db.gz` (142MB, GitHub 한도 100MB 초과). `.gitignore`에 있다.
4. **비밀값은 이 리포에 없다.** `ANTHROPIC_API_KEY`와 `KRDICT_API_KEY`는 reading의 `gutenberg/.env`에 있다. 필요하면 이 리포 루트에 `.env`를 따로 만든다 (gitignored).
5. **JSON을 다시 쓸 때 줄바꿈 형식(CRLF/LF)을 유지한다.** reading에서 Windows가 만든 CRLF 파일을 Mac에서 LF로 다시 썼다가 92만 줄짜리 가짜 diff가 생긴 적이 있다.

## 환경

- Mac (Apple Silicon, 16GB). Python은 루트의 `.venv` (`python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`)
- reading 리포의 uv 환경 `~/reading/gutenberg/.venv`(Python 3.11)에도 wordfreq·spaCy가 있다.
- Windows 작업 PC에서도 쓸 수 있게, 경로는 전부 스크립트 위치 기준 상대경로다. reading 리포를 가리키는 곳은 환경변수 `MARGINALIA_GUTENBERG`로 바꿀 수 있다 (기본 `~/reading/gutenberg`).
- Fly.io 앱: `marginalia-dict` (region nrt, 볼륨 `dict_data` → `/data`)

## 함정 메모

- `dict.db`의 `words`는 kaikki 한 줄 = 한 행이라 (word, pos)가 유일하지 않다 (13,125쌍이 겹침).
- kaikki 발음 선택: US 우선만으로는 부족하다. 축약형(painting → [ˈpeɪnɪŋ]), 근거 없는 파찰음(trouble → tʃ), 방언(/kʉk/), 태그 없는 영국식 기호, form-of / clipping 변형을 따로 다뤄야 한다. 전부 `en-en/scripts/extract_pronunciations.py`에 반영돼 있다.
- KRDICT API는 브라우저 User-Agent가 없으면 WAF에 막히고(`400 Request Blocked`), `num`은 10~100만 허용한다.
- `shared/scripts/build_multilingual_dict.py`는 `raw-wiktextract-data.jsonl`(전 언어 Wiktionary, 10.2M 항목)이 필요한데 이 Mac에는 없다. `shared/data/raw/`에 받아둘 것: https://kaikki.org/dictionary/rawdata.html

- 발음 선택 로직(`en-en/scripts/extract_pronunciations.py`)은 2026-10-17에 사전 전체로 넓히면서 많이 고쳤다. reading의 같은 이름 파일은 그 전 버전이다. 바꿀 때는 `docs/schema.md` §3의 사례(fish, fall, student, thank, onto …)로 회귀를 확인할 것.
- 확인용 페이지: `en-en/app`에서 서버를 띄우고 `/test`.

## 다음 작업

`README.md`의 "다음 작업"을 볼 것. 1순위는 운영 DB의 user_examples를 백업한 뒤 새 dict.db를 배포하는 것이다.
