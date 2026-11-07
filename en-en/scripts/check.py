#!/usr/bin/env python3
"""사전 앱을 한 번에 검사한다. 고치고 나서 커밋 전에 돌린다.

    python en-en/scripts/check.py               # 전부 (~40초. 구문 분석 저장이 없으면 +3분)
    python en-en/scripts/check.py --no-screen   # 브라우저 빼고
    python en-en/scripts/check.py --no-recall   # 재현율 빼고

  1. DB       숙어 표가 있고 비어 있지 않은가
  2. 회귀     docs/idiom_detection.md §6의 문장
  3. 재현율   kaikki 예문 재현율이 기준 아래로 떨어지지 않았는가
  4. API      실제 서버(start.sh와 같은 설정)에 요청을 보낸다
  5. 화면     Chrome으로 눌러 보고 스크린샷을 data/build/check/에 남긴다.
              페이지 스크립트 오류와 좁은 화면의 가로 넘침도 잡는다.
              코드가 도는 것과 화면이 괜찮은 건 다른 문제라서, 찍힌 그림은 사람이 본다

하나라도 실패하면 종료 코드 1이다. 쓰는 DB는 data/build/dict.db다. 운영 DB는 건드리지 않는다.
"""

import argparse
import contextlib
import io
import json
import os
import socket
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
APP = HERE.parent / "app"
sys.path[:0] = [str(HERE), str(APP)]

from eval_idioms import (REGRESSION, DB_PATH, NewDetector, evaluate,  # noqa: E402
                         load_examples, parsed_docs)

SHOTS = DB_PATH.parent / "check"
MODEL = "en_core_web_sm"

# 알려진 실패. sm·lg·trf 모두 up을 불변화사로 분석한다 (docs/idiom_detection.md §8)
KNOWN_FAILS = {"She looked up the street."}

# 재현율 하한. 2026-11-07 값에서 1~2%p 아래다. 규칙을 고치다 조금 흔들리는 건 괜찮고,
# 패턴이나 표가 깨져서 크게 떨어지는 것을 잡으려는 값이다
RECALL_FLOOR = {"연속": 0.85, "자리표시어": 0.82, "불연속": 0.78}

TABLES = ("idioms", "idiom_senses", "idiom_examples", "idiom_forms", "idiom_patterns", "idiom_words")


class Report:
    def __init__(self):
        self.failed = []
        self.passed = 0

    def check(self, name, ok, detail=""):
        print(f"  {'✅' if ok else '❌'} {name}" + (f"  — {detail}" if detail and not ok else ""), flush=True)
        if ok:
            self.passed += 1
        else:
            self.failed.append(name)
        return ok

    def note(self, text):
        print(f"  ⚠️  {text}", flush=True)


def check_db(r):
    print("\n[DB]")
    conn = sqlite3.connect(str(DB_PATH))
    for table in TABLES:
        try:
            n = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        except sqlite3.OperationalError:
            n = 0
        r.check(f"{table} {n:,}행", n > 0, "build_idioms.py를 돌렸는가")
    conn.close()


def check_regression(r, nlp, detector):
    print("\n[회귀]")
    for text, want, forbid in REGRESSION:
        found = detector.detect(nlp(text))
        ok = want <= found and not (forbid & found)
        if text in KNOWN_FAILS:
            r.note(f"알려진 실패 {'(이번엔 통과)' if ok else ''}: {text} → {sorted(found)}")
            continue
        r.check(text, ok, f"찾음 {sorted(found)}, 기대 {sorted(want)}, 금지 {sorted(forbid)}")


def check_recall(r, nlp, detector):
    print("\n[재현율]")
    import spacy
    examples, idioms, names = load_examples(spacy.blank("en").tokenizer)
    quiet = io.StringIO()
    with contextlib.redirect_stdout(quiet):
        docs = parsed_docs(nlp, examples, MODEL, use_cache=True)
        stats = evaluate(detector, docs, examples, idioms, names, 0, 0)
    for kind, floor in RECALL_FLOOR.items():
        rate = stats[kind]["hit"] / max(stats[kind]["n"], 1)
        r.check(f"{kind} {rate:.1%} (하한 {floor:.0%})", rate >= floor)


@contextlib.contextmanager
def running_server():
    """start.sh와 같은 설정으로 서버를 띄운다."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    env = {**os.environ, "DICT_DB_PATH": str(DB_PATH)}
    gunicorn = Path(sys.executable).parent / "gunicorn"
    proc = subprocess.Popen(
        [str(gunicorn), "--bind", f"127.0.0.1:{port}", "--workers", "1", "--threads", "4",
         "--timeout", "30", "server:app"],
        cwd=APP, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(100):
            try:
                urllib.request.urlopen(base + "/api/stats", timeout=2)
                break
            except (urllib.error.URLError, OSError):
                time.sleep(0.2)
        else:
            raise RuntimeError("서버가 뜨지 않았다")
        yield base
    finally:
        proc.terminate()
        proc.wait(timeout=10)


def call(base, path, body=None):
    """(상태 코드, JSON)."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            return res.status, json.load(res)
    except urllib.error.HTTPError as e:
        return e.code, {}


def get(base, path, **params):
    return call(base, path + "?" + urllib.parse.urlencode(params))


def check_api(r, base):
    print("\n[API]")
    detect = "/api/idioms/detect"
    sentence = "She took the cost into account."

    code, d = call(base, detect, {"text": sentence})
    hit = next((x for x in d.get("results", []) if x["idiom"] == "take into account"), None)
    r.check("문장 속 불연속 숙어", code == 200 and hit is not None, str(d)[:120])
    if hit:
        r.check("낀 말과 글자 위치", hit["gap"] == "the cost" and hit["continuous"] is False
                and [sentence[a:b] for a, b in hit["tokens"]] == ["took", "into", "account"], str(hit)[:120])
        r.check("뜻이 같이 온다", bool(hit["senses"]))

    text = "Of course he took a small room and gave it up."
    plain = [x["idiom"] for x in call(base, detect, {"text": text})[1]["results"]]
    every = [x["idiom"] for x in call(base, detect, {"text": text, "levels": ["idiom", "phrasal", "phrase"]})[1]["results"]]
    r.check("기본은 idiom·phrasal만", "give up" in plain and "small room" not in plain, str(plain))
    r.check("levels로 고정 표현도", "small room" in every, str(every))
    in_eyes = call(base, detect, {"text": "There was a look of triumph in his eyes."})[1]["results"]
    r.check("동사 아닌 소유격 숙어는 기본에서 뺀다", not in_eyes, str(in_eyes)[:120])
    r.check("빈 입력은 400", call(base, detect, {})[0] == 400)
    r.check("너무 긴 입력은 400", call(base, detect, {"text": "a " * 1500})[0] == 400)

    _, d = get(base, "/api/lookup", word="took")
    r.check("단어의 숙어 (활용형 → 원형)", any(i["phrase"] == "take on" for i in d["idioms"]["items"]), str(d["idioms"])[:120])
    r.check("숙어 목록 기본 10개", len(d["idioms"]["items"]) == 10 and d["idioms"]["total"] > 10)
    _, d = get(base, "/api/lookup", word="take", idiom_limit=200)
    r.check("idiom_limit", len(d["idioms"]["items"]) == 200)
    for word, want in (("took", True), ("account", True), ("cost", False)):
        _, d = get(base, "/api/lookup", word=word, sentence=sentence)
        got = any(x["idiom"] == "take into account" for x in d.get("in_sentence") or [])
        r.check(f"문장 속 숙어: {word} → {'있음' if want else '없음'}", got == want, str(d.get("in_sentence"))[:120])
    _, d = get(base, "/api/lookup", word="zzzqq")
    r.check("없는 단어", d["results"] == [])

    for query, match, first in (("take into account", "exact", "take into account"),
                                ("took into account", "exact", "take into account"),
                                ("made up his mind", "candidates", "make up one's mind"),
                                ("take the cost into account", "candidates", "take into account"),
                                ("look * up", "candidates", "look up")):
        _, d = get(base, "/api/idiom", phrase=query)
        top = d["results"][0]["phrase"] if d["results"] else None
        r.check(f"숙어 찾기: {query} → {first}", d.get("match") == match and top == first, f"{d.get('match')} {top}")
    _, d = get(base, "/api/idiom", phrase="cup")
    r.check("cup에 up 숙어가 걸리지 않는다", not any(" up" in x["phrase"] for x in d["results"]), str(d["results"])[:120])

    with ThreadPoolExecutor(8) as pool:
        codes = list(pool.map(lambda _: call(base, detect, {"text": sentence})[0], range(32)))
    r.check("동시 요청 32개", set(codes) == {200}, str(set(codes)))


def check_screen(r, base):
    print("\n[화면]")
    from playwright.sync_api import Error, TimeoutError as PlaywrightTimeout, sync_playwright
    SHOTS.mkdir(exist_ok=True)
    errors = []

    def watch(page):
        page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
        page.on("console", lambda m: errors.append(f"console: {m.text}")
                if m.type == "error" and "favicon" not in m.text else None)
        # 사용자 예문은 운영 DB의 데이터다. 검사 대상이 아니고 로컬 DB에는 표가 없을 수 있다
        page.route("**/api/examples*", lambda route: route.fulfill(json={"examples": []}))

    def step(name, fn):
        try:
            fn()
            r.check(name, True)
        except (AssertionError, PlaywrightTimeout, Error) as e:
            r.check(name, False, str(e).split("\n")[0][:140])

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": 1100, "height": 900})
        watch(page)

        def test_word():
            page.goto(base + "/test")
            page.fill("#ctx", "She took the cost into account.")
            page.fill("#q", "took")
            page.press("#q", "Enter")
            page.get_by_text("이 문장에서 이 단어가 든 숙어").wait_for(timeout=8000)
            assert "take into account" in page.inner_text("#out")
            assert "이 단어가 든 숙어 (" in page.inner_text("#out")
            page.screenshot(path=SHOTS / "test_word.png", full_page=True)

        def test_detect():
            page.goto(base + "/test")
            page.fill("#idiomText", "He picked the heavy book up from the floor.")
            page.press("#idiomText", "Enter")
            page.wait_for_selector("#idiomOut mark", timeout=8000)
            marks = page.locator("#idiomOut mark").all_inner_texts()
            assert marks == ["picked", "up"], marks
            page.locator("#idiomOut").scroll_into_view_if_needed()
            page.screenshot(path=SHOTS / "test_detect.png", full_page=True)

        def test_phrase_toggle():
            page.fill("#idiomText", "Of course he took a small room.")
            page.press("#idiomText", "Enter")
            page.get_by_text("찾은 숙어가 없다").wait_for(timeout=8000)
            page.check("#idiomAll")
            page.press("#idiomText", "Enter")
            page.wait_for_selector("#idiomOut .idiom-hit", timeout=8000)
            assert "small room" in page.inner_text("#idiomOut")

        def index_word():
            page.goto(base + "/")
            page.fill("#q", "account")
            page.press("#q", "Enter")
            page.wait_for_selector(".word-idioms", timeout=8000)
            assert "take into account" in page.inner_text(".word-idioms")
            page.locator(".word-idioms").scroll_into_view_if_needed()
            page.screenshot(path=SHOTS / "index_word.png", full_page=True)

        def index_pick():
            page.locator(".word-idioms .idiom-phrase", has_text="take into account").first.click()
            page.wait_for_function("!document.querySelector('.word-idioms')", timeout=8000)
            page.wait_for_selector("#results .idiom-entry", timeout=8000)
            assert "take into account" in page.inner_text("#results")

        def index_candidates():
            page.fill("#q", "look * up")
            page.press("#q", "Enter")
            page.get_by_text("Did you mean one of these").wait_for(timeout=8000)
            page.screenshot(path=SHOTS / "index_candidates.png", full_page=True)
            page.locator(".idiom-phrase").first.click()
            page.wait_for_function("!document.querySelector('.suggestion')", timeout=8000)

        def index_more():
            page.fill("#q", "take")
            page.press("#q", "Enter")
            page.wait_for_selector(".idioms-more", timeout=8000)
            before = page.locator(".word-idioms .idiom-entry").count()
            page.click(".idioms-more")
            page.wait_for_function(f"document.querySelectorAll('.word-idioms .idiom-entry').length > {before}", timeout=8000)

        step("/test: 단어 + 문장 → 숙어 카드", test_word)
        step("/test: 숙어 탐지가 숙어 단어만 강조", test_detect)
        step("/test: 고정 표현 보기", test_phrase_toggle)
        step("/: 단어 페이지의 숙어 목록", index_word)
        step("/: 숙어를 눌러 찾기", index_pick)
        step("/: 후보 보여주고 고르기", index_candidates)
        step("/: 더 보기", index_more)

        phone = browser.new_page(viewport={"width": 390, "height": 800})
        watch(phone)

        def no_overflow(path, query_selector, fill, wait):
            phone.goto(base + path)
            phone.fill(query_selector, fill)
            phone.press(query_selector, "Enter")
            phone.wait_for_selector(wait, timeout=8000)
            width = phone.evaluate("document.documentElement.scrollWidth")
            name = "phone_index.png" if path == "/" else "phone_test.png"
            phone.screenshot(path=SHOTS / name, full_page=True)
            assert width <= 390, f"가로 넘침 {width}px"

        step("휴대폰 폭: / 가로 넘침 없음", lambda: no_overflow("/", "#q", "account", ".word-idioms"))
        step("휴대폰 폭: /test 가로 넘침 없음", lambda: no_overflow("/test", "#idiomText", "She took the cost into account.", "#idiomOut mark"))
        browser.close()

    r.check("페이지 스크립트 오류 없음", not errors, "; ".join(errors[:3])[:200])
    print(f"  스크린샷: {SHOTS}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-screen", action="store_true")
    parser.add_argument("--no-recall", action="store_true")
    args = parser.parse_args()

    import spacy
    t0 = time.time()
    r = Report()
    check_db(r)
    if r.failed:
        print("\n숙어 표가 없어서 멈춘다.")
        return 1

    nlp = spacy.load(MODEL)
    detector = NewDetector(nlp)

    class Names:
        """회귀 사례는 숙어 이름 그대로 비교한다."""
        @staticmethod
        def detect(doc):
            return {x["idiom"].lower() for x in detector.detector.detect(doc)}

    check_regression(r, nlp, Names)
    if not args.no_recall:
        check_recall(r, nlp, detector)
    with running_server() as base:
        check_api(r, base)
        if not args.no_screen:
            check_screen(r, base)

    print(f"\n통과 {r.passed}개, 실패 {len(r.failed)}개 ({time.time() - t0:.0f}초)")
    for name in r.failed:
        print(f"  ❌ {name}")
    return 1 if r.failed else 0


if __name__ == "__main__":
    sys.exit(main())
