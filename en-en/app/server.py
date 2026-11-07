#!/usr/bin/env python3
"""
Marginalia English Dictionary — Web API + UI
SQLite-backed Wiktionary dictionary (1.4M words + 70K idioms)
"""

import math
import sqlite3
import os
import re
import threading
from flask import Flask, request, jsonify, send_from_directory

app = Flask(__name__, static_folder="static")

DB_PATH = os.environ.get("DICT_DB_PATH", "/data/dict.db")

ARCHAIC_NORM = {
    "æ": "ae", "œ": "oe", "ë": "e", "é": "e",
    "è": "e", "à": "a", "â": "a", "î": "i",
    "ô": "o", "û": "u",
}


def normalize(word: str) -> str:
    result = word.lower()
    for old, new in ARCHAIC_NORM.items():
        result = result.replace(old, new)
    return result


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


_TABLES = None


def has_table(conn, name):
    """word_levels·pronunciations는 새 빌드에만 있다. 옛 DB에서도 lookup이 돌게 한다."""
    global _TABLES
    if _TABLES is None:
        _TABLES = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    return name in _TABLES


def levels_for(conn, norm, pos=None):
    """등급 목록. pos를 주면 그 품사 + 품사 구분 없는 체계('*')만."""
    if not has_table(conn, "word_levels"):
        return []
    sql = ("SELECT pos, scheme, level, source, inherited_from FROM word_levels "
           "WHERE word_normalized = ?")
    args = [norm]
    if pos == "name":
        return []                       # 고유명사 항목에는 철자 단위 등급('*')도 붙이지 않는다
    if pos is not None:
        sql += " AND pos IN (?, '*')"
        args.append(pos)
    rows = conn.execute(sql + " ORDER BY scheme, pos", args).fetchall()
    return [dict(r) for r in rows]


def pronunciation_for(conn, norm, pos):
    if not has_table(conn, "pronunciations"):
        return None
    row = conn.execute("SELECT ipa, variety, variant_of FROM pronunciations "
                       "WHERE word_normalized = ? AND pos = ?", (norm, pos)).fetchone()
    return dict(row) if row else None


def init_examples_table():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS user_examples (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            lemma       TEXT NOT NULL,
            surface     TEXT,
            sentence    TEXT NOT NULL,
            cefr        TEXT,
            source_type TEXT DEFAULT 'manual',
            source_label TEXT,
            trigger     TEXT DEFAULT 'manual',
            anon_token  TEXT,
            status      TEXT DEFAULT 'approved',
            score       INTEGER DEFAULT 0,
            flags       INTEGER DEFAULT 0,
            created_at  TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_ue_lemma ON user_examples (lemma, status, score DESC)"
    )
    conn.commit()
    conn.close()


@app.route("/")
def index():
    return send_from_directory("static", "index.html")


@app.route("/test")
def test_page():
    return send_from_directory("static", "test.html")


@app.route("/api/lookup")
def lookup():
    word = request.args.get("word", "").strip()
    if not word:
        return jsonify({"error": "word required"}), 400

    conn = get_db()
    c = conn.cursor()
    norm = normalize(word)

    # Exact match
    c.execute("""
        SELECT id, word, pos, ipa, etymology
        FROM words WHERE word_normalized = ?
        ORDER BY id
    """, (norm,))
    rows = c.fetchall()

    if not rows:
        # Prefix suggestion
        c.execute("""
            SELECT DISTINCT word, pos FROM words
            WHERE word_normalized LIKE ?
            ORDER BY word LIMIT 10
        """, (norm + "%",))
        suggestions = [{"word": r["word"], "pos": r["pos"]} for r in c.fetchall()]
        conn.close()
        return jsonify({"query": word, "results": [], "suggestions": suggestions})

    results = []
    for row in rows:
        c.execute("""
            SELECT sense_num, gloss, example
            FROM senses WHERE word_id = ?
            ORDER BY sense_num
        """, (row["id"],))
        senses = [{"num": s["sense_num"], "gloss": s["gloss"],
                    "example": s["example"]} for s in c.fetchall()]

        results.append({
            "word": row["word"],
            "pos": row["pos"],
            "ipa": row["ipa"],
            "pronunciation": pronunciation_for(conn, norm, row["pos"]),
            "levels": levels_for(conn, norm, row["pos"]),
            "etymology": row["etymology"],
            "senses": senses,
        })

    # Dedupe: keep etymology only on its first occurrence across the result list
    seen_ety = set()
    for r in results:
        ety = r.get("etymology")
        if ety and ety in seen_ety:
            r["etymology"] = None
        elif ety:
            seen_ety.add(ety)

    levels = levels_for(conn, norm)
    out = {"query": word, "results": results, "levels": levels, "suggestions": [],
           "idioms": idioms_of_word(conn, norm, request.args.get("idiom_limit", 10, type=int))}
    sentence = request.args.get("sentence", "").strip()
    if sentence and len(sentence) <= MAX_TEXT:
        out["in_sentence"] = idioms_in_sentence(conn, norm, sentence)
    conn.close()
    return jsonify(out)


@app.route("/api/stats")
def stats():
    """등급·발음 표 현황. 테스트 페이지(static/test.html)가 쓴다."""
    conn = get_db()
    out = {"words": conn.execute("SELECT COUNT(*) FROM words").fetchone()[0]}
    if has_table(conn, "pronunciations"):
        out["pronunciations"] = {r[0] or "?": r[1] for r in conn.execute(
            "SELECT variety, COUNT(*) FROM pronunciations GROUP BY 1 ORDER BY 2 DESC")}
    if has_table(conn, "word_levels"):
        levels = {}
        for scheme, level, source, n in conn.execute(
                "SELECT scheme, level, source = 'inherited', COUNT(*) FROM word_levels "
                "GROUP BY 1, 2, 3 ORDER BY 1, 2"):
            slot = levels.setdefault(scheme, {}).setdefault(level, {"list": 0, "inherited": 0})
            slot["inherited" if source else "list"] = n
        out["levels"] = levels
    conn.close()
    return jsonify(out)


LEVEL_BONUS = {"idiom": 0.06, "phrasal": 0.03, "phrase": 0.0}
LEVEL_ORDER = {"idiom": 0, "phrasal": 1, "phrase": 2}


def lemmas_of(conn, word):
    """단어와 그 원형들 (took → take, minds → mind). 사전의 활용형 연결을 쓴다."""
    forms = {word}
    forms.update(r[0].lower() for r in conn.execute("""
        SELECT l.target FROM words w JOIN word_links l ON l.word_id = w.id
        WHERE w.word_normalized = ? AND l.kind = 'form_of'""", (word,)))
    return forms


def idioms_of_word(conn, word, limit=10):
    """이 단어가 든 숙어. 단어만 찾아도 숙어를 접하게 한다 (took → take의 숙어).

    idiom → phrasal → phrase 순서이고, 같으면 Wiktionary 예문이 많은 쪽이 먼저다.
    예문 수는 흔한 숙어일수록 많다. take는 숙어가 천 개가 넘어서 limit개만 준다.
    """
    if not has_table(conn, "idiom_words"):
        return {"total": 0, "items": []}
    forms = tuple(lemmas_of(conn, word))
    marks = ",".join("?" * len(forms))
    rows = conn.execute(f"""
        SELECT i.phrase, i.meaning, i.level,
               (SELECT COUNT(*) FROM idiom_examples e WHERE e.idiom_id = i.id) AS examples
        FROM idioms i
        WHERE i.id IN (SELECT idiom_id FROM idiom_words WHERE word IN ({marks}))""", forms).fetchall()
    best = {}
    for r in sorted(rows, key=lambda r: (LEVEL_ORDER[r["level"]], -r["examples"], len(r["phrase"]))):
        best.setdefault(r["phrase"], {"phrase": r["phrase"], "meaning": r["meaning"], "level": r["level"]})
    items = list(best.values())
    return {"total": len(items), "items": items[:max(1, min(limit, 200))]}


def idioms_in_sentence(conn, word, sentence):
    """문장에서 찾은 숙어 중 이 단어가 든 것. 책에서 단어를 눌렀을 때 쓴다.

    the cost처럼 숙어 사이에 낀 말을 누르면 나오지 않는다. 탐지기가 없으면 None.
    """
    results = detect_text(sentence)
    if results is None or not has_table(conn, "idiom_words"):
        return None
    forms = tuple(lemmas_of(conn, word))
    marks = ",".join("?" * len(forms))
    return [r for r in results if conn.execute(
        f"SELECT 1 FROM idiom_words WHERE idiom_id = ? AND word IN ({marks}) LIMIT 1",
        (r["idiom_id"], *forms)).fetchone()]


def idiom_candidates(conn, query, limit=15):
    """입력과 단어가 겹치는 숙어 후보. docs/idiom_detection.md §9.

    take account, took into, look * up, take the cost into account를 다 받는다.
    점수 = 입력 중 숙어에 든 비율 × 숙어 중 입력에 든 비율. 단어마다 드물수록 큰
    가중치(idf)를 준다. account가 맞는 것이 into가 맞는 것보다 훨씬 중요하기 때문이다.
    단어 단위로 찾으므로 up이 cup에 걸리지 않는다. spaCy를 쓰지 않는다.
    """
    if not has_table(conn, "idiom_words"):
        return []
    tokens = [t for t in re.findall(r"[a-z0-9'-]+", normalize(query).replace("\u2019", "'"))]
    if not tokens:
        return []
    total = conn.execute("SELECT COUNT(DISTINCT idiom_id) FROM idiom_words").fetchone()[0]

    def idf(word):
        df = conn.execute("SELECT COUNT(*) FROM idiom_words WHERE word = ?", (word,)).fetchone()[0]
        return math.log((total + 1) / (df + 1)) + 1

    weight = {}
    hits = {}                        # idiom_id → {입력 토큰 번호: (숙어 단어, 위치)}
    for k, token in enumerate(tokens):
        forms = lemmas_of(conn, token)
        weight[k] = max(idf(f) for f in forms)
        marks = ",".join("?" * len(forms))
        for iid, word, position in conn.execute(
                f"SELECT idiom_id, word, position FROM idiom_words WHERE word IN ({marks})", tuple(forms)):
            hits.setdefault(iid, {}).setdefault(k, (word, position))

    query_total = sum(weight.values())
    # 입력 쪽 점수로 먼저 줄인다. 흔한 단어 하나만 맞는 숙어가 수천 개일 수 있다
    best = sorted(hits, key=lambda i: -sum(weight[k] for k in hits[i]))[:300]
    scored = {}
    for iid in best:
        matched = hits[iid]
        words = {r[0] for r in conn.execute("SELECT word FROM idiom_words WHERE idiom_id = ?", (iid,))}
        got = {w for w, _ in matched.values()}
        idiom_cover = sum(idf(w) for w in got) / sum(idf(w) for w in words)
        query_cover = sum(weight[k] for k in matched) / query_total
        positions = [p for _, p in (matched[k] for k in sorted(matched))]
        in_order = positions == sorted(positions)
        row = conn.execute("SELECT phrase, meaning, level FROM idioms WHERE id = ?", (iid,)).fetchone()
        score = query_cover * idiom_cover + LEVEL_BONUS[row["level"]] + (0.05 if in_order else 0)
        if len(tokens) > 1 and len(matched) < 2:
            continue                 # 두 단어 이상 넣었으면 두 단어는 맞아야 후보다
        if row["phrase"] not in scored or score > scored[row["phrase"]]["score"]:
            scored[row["phrase"]] = {"phrase": row["phrase"], "meaning": row["meaning"], "level": row["level"],
                                     "score": round(score, 3)}
    return sorted(scored.values(), key=lambda r: (-r["score"], len(r["phrase"])))[:limit]


@app.route("/api/idiom")
def idiom():
    phrase = request.args.get("phrase", "").strip()
    if not phrase:
        return jsonify({"error": "phrase required"}), 400

    conn = get_db()
    c = conn.cursor()
    norm = normalize(phrase)

    c.execute("SELECT phrase, meaning FROM idioms WHERE phrase_normalized = ?", (norm,))
    rows = c.fetchall()

    # 활용형·이형 (took into account → take into account). idiom_forms는 build_idioms.py가 만든다
    if not rows and has_table(conn, "idiom_forms"):
        c.execute("""SELECT DISTINCT i.phrase, i.meaning FROM idiom_forms f
                     JOIN idioms i ON i.id = f.idiom_id WHERE f.form_normalized = ?""", (norm,))
        rows = c.fetchall()

    # Article-stripping fallback
    if not rows:
        stripped = re.sub(r"^(a|an|the)\s+", "", norm)
        if stripped != norm:
            c.execute("SELECT phrase, meaning FROM idioms WHERE phrase_normalized = ?", (stripped,))
            rows = c.fetchall()

    if rows:
        results = [{"phrase": r["phrase"], "meaning": r["meaning"]} for r in rows]
        match = "exact"
    else:
        # 정확히 맞는 게 없으면 후보를 준다. 사용자가 고른다
        results = idiom_candidates(conn, phrase)
        match = "candidates"
    conn.close()
    return jsonify({"query": phrase, "match": match, "results": results})


DEFAULT_LEVELS = ("idiom", "phrasal")
MAX_TEXT = 2000
_DETECTOR = None
_DETECTOR_LOCK = threading.Lock()    # 워커 하나에 스레드 여럿이다 (start.sh). spaCy는 한 번에 하나씩 돌린다


def get_detector():
    """숙어 탐지기. spaCy 모델이 무거워서 처음 쓸 때 읽는다. 없으면 None. 잠금 안에서 부른다."""
    global _DETECTOR
    if _DETECTOR is None:
        try:
            import spacy
            from idiom_detect import IdiomDetector
            _DETECTOR = IdiomDetector(db_path=DB_PATH, nlp=spacy.load("en_core_web_sm", exclude=["ner"]))
        except (ImportError, OSError, sqlite3.OperationalError) as e:
            app.logger.warning("idiom detector unavailable: %s", e)
            return None
    return _DETECTOR


def detect_text(text, levels=None):
    """문장 속 숙어. 기본은 idiom·phrasal만. 탐지기가 없으면 None."""
    with _DETECTOR_LOCK:
        detector = get_detector()
        if detector is None:
            return None
        results = detector.find(text)
    levels = levels or DEFAULT_LEVELS
    return [r for r in results if r["level"] in levels]


@app.route("/api/idioms/detect", methods=["POST"])
def idioms_detect():
    """문장 속 숙어 찾기. docs/idiom_detection.md §7.

    기본은 idiom·phrasal만 준다. 고정 표현까지 보려면 levels에 phrase를 넣는다.
    """
    body = request.get_json(silent=True) or {}
    text = (body.get("text") or "").strip()
    if not text:
        return jsonify({"error": "text required"}), 400
    if len(text) > MAX_TEXT:
        return jsonify({"error": f"text too long (max {MAX_TEXT})"}), 400
    results = detect_text(text, body.get("levels"))
    if results is None:
        return jsonify({"error": "idiom detector not available"}), 503
    return jsonify({"text": text, "results": results})


@app.route("/api/search")
def search():
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify({"error": "q required"}), 400

    conn = get_db()
    c = conn.cursor()
    sql_pattern = normalize(q).replace("*", "%").replace("?", "_")

    c.execute("""
        SELECT DISTINCT word, pos FROM words
        WHERE word_normalized LIKE ?
        ORDER BY word LIMIT 30
    """, (sql_pattern,))
    results = [{"word": r["word"], "pos": r["pos"]} for r in c.fetchall()]
    conn.close()
    return jsonify({"query": q, "results": results})


# ── Reader Example Harvest (design/64) ──────────────────────────────────────

@app.route("/api/examples")
def get_examples():
    lemma = request.args.get("lemma", "").strip().lower()
    if not lemma:
        return jsonify({"error": "lemma required"}), 400
    limit = min(int(request.args.get("limit", 5)), 20)

    conn = get_db()
    c = conn.cursor()
    c.execute("""
        SELECT id, lemma, sentence, cefr, source_type, source_label, score, created_at
        FROM user_examples
        WHERE lemma = ? AND status = 'approved'
        ORDER BY score DESC, created_at DESC
        LIMIT ?
    """, (lemma, limit))
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return jsonify({"lemma": lemma, "examples": rows})


@app.route("/api/examples/contribute", methods=["POST"])
def contribute():
    data = request.get_json(silent=True) or {}
    lemma = (data.get("lemma") or "").strip().lower()
    sentence = (data.get("sentence") or "").strip()
    anon_token = (data.get("anon_token") or "")[:64]

    if not lemma:
        return jsonify({"error": "lemma required"}), 400
    if not sentence:
        return jsonify({"error": "sentence required"}), 400

    # Basic quality filter
    if len(sentence) < 10 or len(sentence) > 400:
        return jsonify({"error": "sentence length must be 10–400 chars"}), 422
    if lemma not in sentence.lower():
        return jsonify({"error": "lemma not found in sentence"}), 422

    conn = get_db()
    c = conn.cursor()

    # Duplicate check
    c.execute(
        "SELECT id FROM user_examples WHERE lemma = ? AND sentence = ?",
        (lemma, sentence)
    )
    if c.fetchone():
        conn.close()
        return jsonify({"error": "duplicate"}), 409

    # Flood check: same anon_token, same lemma, last 24h
    if anon_token:
        c.execute("""
            SELECT COUNT(*) FROM user_examples
            WHERE lemma = ? AND anon_token = ?
              AND created_at > datetime('now', '-1 day')
        """, (lemma, anon_token))
        if c.fetchone()[0] >= 3:
            conn.close()
            return jsonify({"error": "too many contributions for this word today"}), 429

    c.execute("""
        INSERT INTO user_examples
            (lemma, surface, sentence, cefr, source_type, source_label, trigger, anon_token)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        lemma,
        data.get("surface", lemma),
        sentence,
        data.get("cefr"),
        data.get("source_type", "manual"),
        data.get("source_label"),
        data.get("trigger", "manual"),
        anon_token,
    ))
    new_id = c.lastrowid
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "id": new_id}), 201


@app.route("/api/examples/<int:example_id>/vote", methods=["POST"])
def vote(example_id):
    data = request.get_json(silent=True) or {}
    value = 1 if data.get("value", 1) > 0 else -1
    conn = get_db()
    conn.execute(
        "UPDATE user_examples SET score = score + ? WHERE id = ? AND status = 'approved'",
        (value, example_id)
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/examples/<int:example_id>/flag", methods=["POST"])
def flag_example(example_id):
    conn = get_db()
    conn.execute(
        "UPDATE user_examples SET flags = flags + 1 WHERE id = ?",
        (example_id,)
    )
    # Auto-reject if flagged 3+ times
    conn.execute(
        "UPDATE user_examples SET status = 'rejected' WHERE id = ? AND flags >= 3",
        (example_id,)
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


if __name__ == "__main__":
    # Local dev
    if not os.path.exists(DB_PATH):
        DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "build", "dict.db")
    init_examples_table()
    app.run(host="0.0.0.0", port=8080, debug=True)
