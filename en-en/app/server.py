#!/usr/bin/env python3
"""
Marginalia English Dictionary — Web API + UI
SQLite-backed Wiktionary dictionary (1.4M words + 70K idioms)
"""

import sqlite3
import os
import re
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

    conn.close()
    return jsonify({"query": word, "results": results, "suggestions": []})


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

    # Article-stripping fallback
    if not rows:
        stripped = re.sub(r"^(a|an|the)\s+", "", norm)
        if stripped != norm:
            c.execute("SELECT phrase, meaning FROM idioms WHERE phrase_normalized = ?", (stripped,))
            rows = c.fetchall()

    # Keyword match fallback — find idioms containing ALL query words
    if not rows:
        words = norm.split()
        if len(words) >= 2:
            conditions = " AND ".join(["phrase_normalized LIKE ?"] * len(words))
            params = ["%" + w + "%" for w in words]
            c.execute(f"""
                SELECT phrase, meaning FROM idioms
                WHERE {conditions} LIMIT 20
            """, params)
            rows = c.fetchall()

    # Partial match fallback (single substring)
    if not rows:
        c.execute("""
            SELECT phrase, meaning FROM idioms
            WHERE phrase_normalized LIKE ? LIMIT 10
        """, ("%" + norm + "%",))
        rows = c.fetchall()

    results = [{"phrase": r["phrase"], "meaning": r["meaning"]} for r in rows]
    conn.close()
    return jsonify({"query": phrase, "results": results})


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
        DB_PATH = os.path.join(os.path.dirname(__file__), "..", "dict.db")
    init_examples_table()
    app.run(host="0.0.0.0", port=8080, debug=True)
