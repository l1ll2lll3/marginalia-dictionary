# en-en — 영영사전

Wiktionary(kaikki.org) 기반 영어 사전. 1.4M 항목 + 숙어 70K. 운영 중: https://marginalia-dict.fly.dev/

## 파일

| 경로 | 내용 | git |
|---|---|---|
| `scripts/build_dict_db.py` | `data/raw/kaikki-en.jsonl` + `english_idioms.json` → `data/build/dict.db` (words, senses, idioms, word_links, pronunciations) | ✅ |
| `scripts/build_levels.py` | dict.db에 `word_levels` 추가 (CEFR + 교육과정). `--check went colour`로 조회 | ✅ |
| `scripts/parse_kr_curriculum.py` | 교육과정 PDF → `data/kr_curriculum/moe_2022_basic_vocab.csv` | ✅ |
| `scripts/dict.py` | CLI 조회 (`dict.py bourdon`, `dict.py --search "medi*"`) | ✅ |
| `scripts/extract_pronunciations.py` | 발음 선택 로직 `_pick_ipa()` (build_dict_db가 import). 단독 실행은 `--book`(reading의 book_package.json) 표제어용 캐시 생성 | ✅ |
| `scripts/cefr_grading.py` | `Grader().grade(lemma, spaCy_pos)` → (등급, 출처, 품사일치) | ✅ |
| `app/` | Flask 웹앱 + Fly.io 설정 (`app/README.md`에 원래 문서) | ✅ |
| `data/cefr/` | CEFR-J 1.5, Octanove 1.0 CSV + `LICENSE-NOTE.txt` | ✅ |
| `data/kr_curriculum/moe_2022_basic_vocab.csv` | 2022 교육과정 기본 어휘 3,001 단어군 → 3,283행 (word, level, family, kind) | ✅ |
| `data/raw/kr_curriculum_2022.pdf` | 교육과정 원문 PDF (`fetch_data.py`) | ❌ |
| `data/build/pronunciations_en.json` | 발음 캐시 7,736쌍 (`lemma\|POS` → ipa, variety, variant_of) | ✅ |
| `data/raw/kaikki-en.jsonl` | Wiktionary 영어 전체 덤프 3.1GB (2026-09 다운로드) | ❌ |
| `data/raw/english_idioms.json` | wiktextract 숙어 69,651개 (11MB) | ✅ |
| `data/build/dict.db` / `.gz` | 빌드 결과 319MB / 142MB | ❌ |

## 다른 컴퓨터에서 받기

```bash
python ../fetch_data.py                  # kaikki-en.jsonl(3.3GB) + 교육과정 PDF, 끊기면 이어받음
python scripts/build_dict_db.py          # → data/build/dict.db (~45초)
python scripts/build_levels.py           # + word_levels (~10초)
gzip -k data/build/dict.db               # 배포용 dict.db.gz
```

## 웹앱

```bash
cd app && DICT_DB_PATH=$PWD/../data/build/dict.db ../../.venv/bin/python server.py
```

- 사전 화면: http://localhost:8080/
- **데이터 확인 페이지: http://localhost:8080/test** (`static/test.html`) — 품사별 발음, 변종(us/uk…), CEFR·교육과정 등급과 상속 출처, DB 현황
- API: `/api/lookup?word=went` 응답의 각 항목에 `pronunciation`, `levels`가 있고, 최상위 `levels`는 철자 전체의 등급이다. `/api/stats`는 표 현황.

DB 파일이 430MB라 브라우저가 직접 읽을 수 없어서, 테스트 페이지도 서버를 통해 본다.

배포는 `app/`에서 `fly deploy` 한다. Dockerfile이 `dict.db.gz`를 같은 폴더에서 찾으므로, 먼저 `cp data/build/dict.db.gz app/`을 하고 끝나면 지운다.

> ⚠️ 새 `dict.db.gz`를 배포하면 `start.sh`가 볼륨의 DB를 덮어써서 `user_examples`(사용자 예문)가 사라진다. 먼저 운영 DB에서 백업할 것: `fly ssh console -a marginalia-dict -C "sqlite3 /data/dict.db .dump user_examples"`
