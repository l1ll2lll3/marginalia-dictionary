# shared — 여러 언어쌍을 한 번에 만드는 것

`scripts/build_multilingual_dict.py` → `data/multilingual_dict.json` (29MB)
- 영어 kaikki의 translations → en_ko, en_zh
- 전 언어 Wiktionary `raw-wiktextract-data.jsonl`(10.2M 항목)의 한국어·중국어 항목 → ko_en, zh_en, 역방향
- 그 밖에 ko_zh, zh_ko

`raw-wiktextract-data.jsonl`은 이 Mac에 없다. `data/raw/`에 받아야 다시 빌드할 수 있다: https://kaikki.org/dictionary/rawdata.html
