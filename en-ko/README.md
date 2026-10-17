# en-ko — 영한사전

현재: `data/en_ko_dict.json` 20,286개. `{ "dictionary": {"ko": ["사전", …], "src": "kaikki"} }`

| 스크립트 | 하는 일 |
|---|---|
| `scripts/build_en_ko_dict.py` | `en-en/data/raw/kaikki-en.jsonl`의 translations에서 한국어만 뽑는다 |
| `scripts/merge_en_ko_dict.py` | 합본: reading 책별 Claude gloss 캐시(`*_enrich_cache.json`, 최우선) > `shared/data/multilingual_dict.json` en_ko > kaikki. 캐시 위치는 `MARGINALIA_GUTENBERG` (기본 `~/reading/gutenberg`) |

reading의 어휘책(`make_vocab_book.py` 등)이 `ko_gloss`를 이 사전에서 찾는다 (무료·결정적).
