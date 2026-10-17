# ko-ko — 한한사전

현재: `data/ko-extract.jsonl.gz` 한국어 Wiktionary(wiktextract) 355,243 항목. reading의 `sense_select.py`(문맥 뜻 선택)가 이 파일을 쓴다. KRDICT(국립국어원 한국어기초사전) 파이프라인 예정, 등급(초급·중급·고급) 포함.

DB로 만들 때는 en-en과 같은 구조(`words`/`senses`/`word_levels`/`pronunciations`)를 쓴다. `docs/schema.md` 참고.
