# en-en — 영영사전

Wiktionary(kaikki.org) 기반 영어 사전. 1.4M 항목 + 숙어 70K. 운영 중: https://marginalia-dict.fly.dev/

## 파일

| 경로 | 내용 | git |
|---|---|---|
| `scripts/build_dict_db.py` | `data/raw/kaikki-en.jsonl` + `english_idioms.json` → `data/build/dict.db` | ✅ |
| `scripts/dict.py` | CLI 조회 (`dict.py bourdon`, `dict.py --search "medi*"`) | ✅ |
| `scripts/extract_pronunciations.py` | (단어, 품사)별 미국식 발음 선택. 지금은 `--book`(reading의 book_package.json 절대경로) 표제어만 대상 | ✅ |
| `scripts/cefr_grading.py` | `Grader().grade(lemma, spaCy_pos)` → (등급, 출처, 품사일치) | ✅ |
| `app/` | Flask 웹앱 + Fly.io 설정 (`app/README.md`에 원래 문서) | ✅ |
| `data/cefr/` | CEFR-J 1.5, Octanove 1.0 CSV + `LICENSE-NOTE.txt` | ✅ |
| `data/build/pronunciations_en.json` | 발음 캐시 7,736쌍 (`lemma\|POS` → ipa, variety, variant_of) | ✅ |
| `data/raw/kaikki-en.jsonl` | Wiktionary 영어 전체 덤프 3.1GB (2026-09 다운로드) | ❌ |
| `data/raw/english_idioms.json` | wiktextract 숙어 69,651개 (11MB) | ✅ |
| `data/build/dict.db` / `.gz` | 빌드 결과 319MB / 142MB | ❌ |

## 다른 컴퓨터에서 받기

```bash
curl -L -A "Mozilla/5.0" -o data/raw/kaikki-en.jsonl \
  https://kaikki.org/dictionary/English/kaikki.org-dictionary-English.jsonl
python scripts/build_dict_db.py          # → data/build/dict.db (~3분)
gzip -k data/build/dict.db               # 배포용 dict.db.gz
```

## 웹앱

```bash
DICT_DB_PATH=$PWD/data/build/dict.db python app/server.py
```

배포는 `app/`에서 `fly deploy` 한다. Dockerfile이 `dict.db.gz`를 같은 폴더에서 찾으므로, 먼저 `cp data/build/dict.db.gz app/`을 하고 끝나면 지운다.

> ⚠️ 새 `dict.db.gz`를 배포하면 `start.sh`가 볼륨의 DB를 덮어써서 `user_examples`(사용자 예문)가 사라진다. 먼저 운영 DB에서 백업할 것: `fly ssh console -a marginalia-dict -C "sqlite3 /data/dict.db .dump user_examples"`
