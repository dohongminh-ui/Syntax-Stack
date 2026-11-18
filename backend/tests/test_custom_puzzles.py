"""Paste-your-own-code puzzles: generation, storage, API, and the sandbox boundary."""
import json
import sqlite3
import threading
import time

import pytest

from app import bank, custom, custom_gen, sandbox
from app import validator as V

LOOP = "total = 0\nfor i in range(1, 5):\n    total = total + i\nprint(total)"
TINY = "x = 5\nprint(x)"
ALL_TYPES = {"predict_output", "find_bug", "fill_blank", "parsons"}


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(custom, "DB_PATH", tmp_path / "custom.sqlite")
    monkeypatch.setattr(custom, "_db_path_cache", None)
    custom.reset_rate_limits()
    yield
    custom.reset_rate_limits()


def create(client, code=LOOP, **extra):
    return client.post("/api/custom/sets", json={"code": code, **extra})


def rows_of(body):
    return {p["type"]: custom.get_puzzle(p["id"]) for p in body["puzzles"]}


def correct_body(row, reveal=True):
    d = row["data"]
    if row["type"] == "parsons":
        return {"order": [{"line_id": s["line_id"], "indent": s["indent"]} for s in d["solution"]], "reveal": reveal}
    return {"option_id": next(o["id"] for o in d["options"] if o["correct"]), "reveal": reveal}


def wrong_body(row, reveal=True):
    d = row["data"]
    if row["type"] == "parsons":
        return {"order": [{"line_id": l["id"], "indent": 0} for l in d["lines"]], "reveal": reveal}
    return {"option_id": next(o["id"] for o in d["options"] if not o["correct"]), "reveal": reveal}


# --------------------------------------------------------------------------- happy path


def test_loop_program_yields_all_four_verified_puzzles(client):
    r = create(client)
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {"id", "topic", "code", "expected_output", "puzzles", "skipped"}
    assert len(body["id"]) == 8 and body["id"] == body["id"].lower()
    assert body["topic"] == "loops" and body["expected_output"] == "10" and body["code"] == LOOP
    assert [p["type"] for p in body["puzzles"]] == ["predict_output", "find_bug", "fill_blank", "parsons"]
    assert body["skipped"] == []
    for n, p in enumerate(body["puzzles"], 1):
        assert p["id"] == f"c-{body['id']}-{n}"
        assert p["template_id"] == "custom" and p["tier"] == 1 and p["topic"] == "loops"


def test_every_option_is_verified_by_running_it(client):
    rows = rows_of(create(client).json())
    assert set(rows) == ALL_TYPES
    expected = rows["predict_output"]["expected_output"]

    pred = rows["predict_output"]["data"]["options"]
    texts = [o["text"] for o in pred]
    assert len(pred) == 4 and len(set(texts)) == 4
    assert [o["text"] for o in pred if o["correct"]] == [expected]
    assert V.normalize_output(V.run_program(rows["predict_output"]["code"]).output) == expected

    fill = rows["fill_blank"]
    assert fill["code"].count("___") == 1
    opts = fill["data"]["options"]
    assert len(opts) == 4 and len({o["text"] for o in opts}) == 4
    for o in opts:
        diag = V.diagnose(fill["code"].replace("___", o["text"]), expected)
        assert diag.passed == o["correct"]
    assert sum(o["correct"] for o in opts) == 1

    bug = rows["find_bug"]["data"]
    lines = bug["lines"]
    opts = bug["options"]
    assert len(opts) == 4 and len({(o["line_id"], o["text"]) for o in opts}) == 4
    assert len({o["line_id"] for o in opts}) >= 2 and len({o["line_id"] for o in opts[:3]}) >= 2
    for o in opts:
        edited = [(l["indent"], o["text"] if l["id"] == o["line_id"] else l["text"]) for l in lines]
        code = "\n".join("    " * ind + t for ind, t in edited)
        assert V.diagnose(code, expected).passed == o["correct"]
    assert [o["line_id"] for o in opts if o["correct"]] == [bug["bug_line"]]
    buggy = "\n".join("    " * l["indent"] + l["text"] for l in lines)
    assert not V.diagnose(buggy, expected).passed

    pars = rows["parsons"]["data"]
    text = {l["id"]: l["text"] for l in pars["lines"]}
    solved = "\n".join("    " * s["indent"] + text[s["line_id"]] for s in pars["solution"])
    assert V.diagnose(solved, expected).passed
    shown = "\n".join(l["text"] for l in pars["lines"])
    assert not V.diagnose(shown, expected).passed


def test_answer_endpoint_correct_and_wrong_for_every_type(client):
    body = create(client).json()
    rows = rows_of(body)
    for typ, row in rows.items():
        ok = client.post(f"/api/puzzle/{row['id']}/answer", json=correct_body(row))
        assert ok.status_code == 200, (typ, ok.text)
        j = ok.json()
        assert j["correct"] is True and j["solution_code"] == LOOP and j["explanation"]
        bad = client.post(f"/api/puzzle/{row['id']}/answer", json=wrong_body(row))
        assert bad.status_code == 200, (typ, bad.text)
        j = bad.json()
        assert j["correct"] is False and j["error_group"] and j["message"]
        assert j["solution_code"] == LOOP  # reveal=true
        hidden = client.post(f"/api/puzzle/{row['id']}/answer", json=wrong_body(row, reveal=False)).json()
        assert hidden["correct"] is False and hidden["solution_code"] is None and hidden["explanation"] is None


def test_answer_errors_for_custom_ids(client):
    body = create(client).json()
    pid = body["puzzles"][0]["id"]
    assert client.post(f"/api/puzzle/{pid}/answer", json={"option_id": "zzz"}).status_code == 422
    assert client.post(f"/api/puzzle/c-{body['id']}-9/answer", json={"option_id": "a"}).status_code == 404
    assert client.post("/api/puzzle/c-aaaaaaaa-1/answer", json={"option_id": "a"}).status_code == 404
    assert client.post("/api/puzzle/c-nonsense/answer", json={"option_id": "a"}).status_code == 404
    parsons = next(p for p in body["puzzles"] if p["type"] == "parsons")
    bad_order = {"order": [{"line_id": "l1", "indent": 5}] + [{"line_id": f"l{i}", "indent": 0} for i in (2, 3, 4)]}
    assert client.post(f"/api/puzzle/{parsons['id']}/answer", json=bad_order).status_code == 422


def test_hint_and_explain_work_for_custom_ids(client):
    body = create(client).json()
    rows = rows_of(body)
    for row in rows.values():
        for level in (1, 2, 3):
            h = client.get(f"/api/puzzle/{row['id']}/hint", params={"level": level}).json()
            assert h["level"] == level and h["source"] == "canned" and len(h["text"]) > 10
        ex = client.post(f"/api/puzzle/{row['id']}/explain", json=wrong_body(row))
        assert ex.status_code == 200, ex.text
        assert ex.json()["source"] == "canned" and ex.json()["text"]
        done = client.post(f"/api/puzzle/{row['id']}/explain", json=correct_body(row))
        assert done.status_code == 422
    assert client.get("/api/puzzle/c-aaaaaaaa-1/hint", params={"level": 1}).status_code == 404


def test_rematch_is_not_available_for_custom_puzzles(client):
    pid = create(client).json()["puzzles"][0]["id"]
    r = client.get(f"/api/puzzle/{pid}/rematch")
    assert r.status_code == 422 and r.json()["detail"] == "Câu đố tự tạo không có bản luyện lại."


def test_topic_is_inferred_from_the_ast(client):
    cases = {
        "def f(n):\n    return n + 1\nprint(f(2))\nprint(f(3))": "functions",
        "n = 3\nif n > 2:\n    print(n)\nelse:\n    print(0)": "conditions",
        "a = 4\nb = a + 2\nprint(b)": "variables",
    }
    for code, topic in cases.items():
        r = create(client, code)
        assert r.status_code == 200, (code, r.text)
        assert r.json()["topic"] == topic


def test_comments_blank_lines_and_crlf_are_normalised(client):
    code = "# demo\r\ntotal = 0   # start\r\n\r\nfor i in range(1, 5):\r\n    total = total + i\r\nprint(total)\r\n"
    r = create(client, code)
    assert r.status_code == 200
    assert r.json()["code"] == LOOP


def test_tiny_program_skips_types_and_says_why(client):
    r = create(client, TINY)
    assert r.status_code == 200
    body = r.json()
    types = {p["type"] for p in body["puzzles"]}
    skipped = {s["type"]: s["reason"] for s in body["skipped"]}
    assert "fill_blank" in types
    assert "parsons" in skipped and "predict_output" in skipped
    assert types | set(skipped) == ALL_TYPES and not types & set(skipped)
    assert all(isinstance(r, str) and r for r in skipped.values())


# --------------------------------------------------------------------------- 422 reasons


BAD_INPUTS = {
    "too_long": ("x = 1\n" * 140 + "print(x)", "quá dài"),
    "too_few_lines": ("print(1)", "ít nhất 2 dòng"),
    "too_many_lines": ("\n".join(f"v{i} = {i}" for i in range(16)), "tối đa 15 dòng"),
    "tab": ("for i in range(3):\n\tprint(i)", "Tab"),
    "bad_indent": ("for i in range(3):\n  print(i)", "bội số của 4"),
    "import": ("import os\nprint(1)", "import"),
    "attribute": ("x = 'a'\nprint(x.upper())", "chưa được hỗ trợ"),
    "underscore": ("_x = 1\nprint(_x)", "gạch dưới"),
    "syntax": ("for i in range(3)\n    print(i)", "dấu hai chấm"),
    "runtime": ("x = 1\nprint(x / 0)", "chia cho 0"),
    "no_output": ("x = 1\ny = x + 1", "không in ra gì"),
    "too_much_output": ("for i in range(10):\n    print(i)", "Đầu ra quá dài"),
    "endless_loop": ("while True:\n    pass", "quá lâu"),
    "string_times": ('s = "ab"\nt = s * 5\nprint(t)', "nhân chuỗi"),
    "list_times": ("x = [0] * 4\nprint(len(x))", "nhân chuỗi"),
    "fstring_times": ('n = 3\nprint(f"{n}" * 2)', "nhân chuỗi"),
    "big_constant": ("x = 5000000\nprint(x)", "số quá lớn"),
}


@pytest.mark.parametrize("name", sorted(BAD_INPUTS))
def test_422_reasons(client, name):
    code, fragment = BAD_INPUTS[name]
    r = create(client, code)
    assert r.status_code == 422, r.text
    detail = r.json()["detail"]
    assert isinstance(detail, str) and fragment in detail, detail


def test_nothing_generated_is_422(client):
    r = create(client, 'print("a")\nprint("b")')
    assert r.status_code == 422
    assert "Không tạo được câu đố nào" in r.json()["detail"]


def test_missing_code_and_bad_level_are_422(client):
    assert client.post("/api/custom/sets", json={}).status_code == 422
    assert create(client, LOOP, level="expert").status_code == 422


def test_too_long_is_vietnamese_detail_not_a_pydantic_list(client):
    r = create(client, "x" * 5000)
    assert r.status_code == 422 and isinstance(r.json()["detail"], str)


# --------------------------------------------------------------------------- rate limit


def test_rate_limit_is_ten_sets_per_hour_per_client(client):
    for _ in range(custom.RATE_LIMIT):
        assert create(client, TINY).status_code == 200
    r = create(client, TINY)
    assert r.status_code == 429 and "một giờ" in r.json()["detail"]
    other = client.post("/api/custom/sets", json={"code": TINY}, headers={"cf-connecting-ip": "203.0.113.9"})
    assert other.status_code == 200


def test_rejected_input_does_not_use_up_the_quota(client):
    for _ in range(15):
        assert create(client, "print(1)").status_code == 422
    assert create(client, TINY).status_code == 200


def test_rate_limit_window_slides(client, monkeypatch):
    now = time.time()
    monkeypatch.setattr(custom, "_now", lambda: now)
    for _ in range(custom.RATE_LIMIT):
        assert create(client, TINY).status_code == 200
    assert create(client, TINY).status_code == 429
    monkeypatch.setattr(custom, "_now", lambda: now + custom.RATE_WINDOW_S + 1)
    assert create(client, TINY).status_code == 200


# --------------------------------------------------------------------------- storage


def test_get_set_round_trip_and_levels(client):
    created = create(client).json()
    got = client.get(f"/api/custom/sets/{created['id']}")
    assert got.status_code == 200
    body = got.json()
    assert body["id"] == created["id"]
    # the shared view must not carry the source or its output: together they answer every puzzle
    assert body["code"] is None and body["expected_output"] is None
    assert created["code"] and created["expected_output"]
    assert [p["id"] for p in body["puzzles"]] == [p["id"] for p in created["puzzles"]]
    assert {**body, "code": created["code"], "expected_output": created["expected_output"]} == created
    beginner = client.get(f"/api/custom/sets/{created['id']}", params={"level": "beginner"}).json()
    adv = client.get(f"/api/custom/sets/{created['id']}", params={"level": "advanced"}).json()
    pred_b = next(p for p in beginner["puzzles"] if p["type"] == "predict_output")
    pred_a = next(p for p in adv["puzzles"] if p["type"] == "predict_output")
    assert len(pred_b["options"]) == 3 and len(pred_a["options"]) == 4
    # a beginner always still sees the correct answer
    row = custom.get_puzzle(pred_b["id"])
    correct = next(o["id"] for o in row["data"]["options"] if o["correct"])
    assert correct in {o["id"] for o in pred_b["options"]}
    assert client.get(f"/api/custom/sets/{created['id']}", params={"level": "x"}).status_code == 422


def test_create_with_level_changes_the_views(client):
    body = create(client, level="beginner").json()
    pred = next(p for p in body["puzzles"] if p["type"] == "predict_output")
    assert len(pred["options"]) == 3


def test_unknown_or_malformed_set_is_404(client):
    assert client.get("/api/custom/sets/aaaaaaaa").status_code == 404
    assert client.get("/api/custom/sets/not-an-id").status_code == 404
    assert client.get("/api/custom/sets/AAAAAAAA").status_code == 404


def test_sets_expire_after_30_days_and_are_purged(client, monkeypatch, tmp_path):
    body = create(client).json()
    pid = body["puzzles"][0]["id"]
    db = tmp_path / "custom.sqlite"

    def count():
        con = sqlite3.connect(db)
        try:
            return con.execute("SELECT COUNT(*) FROM custom_sets").fetchone()[0]
        finally:
            con.close()

    assert count() == 1
    later = time.time() + custom.TTL_S + 60
    monkeypatch.setattr(custom, "_now", lambda: later)
    assert client.get(f"/api/custom/sets/{body['id']}").status_code == 404  # expired even before purge
    assert client.post(f"/api/puzzle/{pid}/answer", json={"option_id": "a"}).status_code == 404
    assert count() == 1
    assert custom.purge_expired() == 1 and count() == 0


def test_creating_a_set_purges_expired_ones(client, monkeypatch, tmp_path):
    old = create(client).json()["id"]
    later = time.time() + custom.TTL_S + 60
    monkeypatch.setattr(custom, "_now", lambda: later)
    new = create(client, TINY).json()["id"]
    con = sqlite3.connect(tmp_path / "custom.sqlite")
    ids = [r[0] for r in con.execute("SELECT id FROM custom_sets")]
    con.close()
    assert ids == [new] and old not in ids


def test_stored_row_keeps_source_and_a_client_hash_not_the_ip(client, tmp_path):
    r = client.post("/api/custom/sets", json={"code": LOOP}, headers={"cf-connecting-ip": "198.51.100.7"})
    assert r.status_code == 200
    con = sqlite3.connect(tmp_path / "custom.sqlite")
    row = con.execute("SELECT source_code, client_hash, puzzles FROM custom_sets").fetchone()
    con.close()
    assert row[0] == LOOP and len(row[1]) == 16 and "198.51.100.7" not in json.dumps(row)


# --------------------------------------------------------------------------- no leaks

FORBIDDEN_KEYS = {"correct", "solution_code", "explanation", "hints", "bug_line", "solution", "distractors",
                  "actual_output", "note", "group", "name", "message", "buggy_output", "buggy_message",
                  "debug_only"}
VIEW_KEYS = {"id", "template_id", "topic", "type", "tier", "prompt", "code", "expected_output", "lines", "options"}


def _walk_keys(node):
    if isinstance(node, dict):
        for k, v in node.items():
            yield k
            yield from _walk_keys(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk_keys(v)


@pytest.mark.parametrize("level", ["beginner", "intermediate", "advanced"])
def test_public_views_never_leak(client, level):
    body = create(client, level=level).json()
    for p in body["puzzles"]:
        assert set(p) == VIEW_KEYS
        assert not FORBIDDEN_KEYS & set(_walk_keys(p)), p["type"]
        if p["type"] == "predict_output":
            assert p["expected_output"] is None
        if p["type"] in ("parsons", "find_bug"):
            assert p["code"] is None
        if p["type"] == "parsons":
            assert p["options"] is None and all(set(l) == {"id", "text"} for l in p["lines"])
    again = client.get(f"/api/custom/sets/{body['id']}", params={"level": level}).json()
    for p in again["puzzles"]:
        assert not FORBIDDEN_KEYS & set(_walk_keys(p))


# --------------------------------------------------------------------------- sandbox boundary


def test_sandbox_timeout_kills_an_uninterruptible_program(client, monkeypatch):
    # sum(range(10**12)) is one C-level call: the validator's step counter cannot stop it, the child's
    # wall-clock limit must.
    hang = "n = 1000000 * 1000000\nprint(sum(range(n)))"
    code, _ = custom_gen.prepare_source(hang)  # passes every static rule on purpose
    t0 = time.monotonic()
    with pytest.raises(sandbox.SandboxError) as e:
        sandbox.generate(code, timeout=1.0)
    assert e.value.kind == "timeout" and time.monotonic() - t0 < 4

    monkeypatch.setattr(sandbox, "GENERATION_TIMEOUT_S", 1.0)
    r = create(client, hang)
    assert r.status_code == 422 and "quá lâu" in r.json()["detail"]
    # the server is fine afterwards
    assert client.get("/api/health").status_code == 200
    assert create(client).status_code == 200


def test_answer_check_that_hangs_is_a_wrong_answer_not_a_hang(monkeypatch):
    monkeypatch.setattr(sandbox, "CHECK_TIMEOUT_S", 1.0)
    diag = sandbox.diagnose("n = 1000000 * 1000000\nprint(sum(range(n)))", "10")
    assert diag.passed is False and diag.run is not None and diag.run.ok is False
    assert sandbox.diagnose(LOOP, "10").passed is True
    assert sandbox.diagnose(LOOP, "11").passed is False


def test_big_string_multiplication_is_rejected_before_running(client, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("must not start a child for rejected code")
    monkeypatch.setattr(sandbox, "run_job", boom)
    for code in ('x = "a" * 999999\nprint(len(x))', 'y = "ab"\nx = y * 999999 * 999\nprint(len(x))',
                 'n = 999999\ns = str(n) * n\nprint(len(s))'):
        r = create(client, code)
        assert r.status_code == 422 and "nhân chuỗi" in r.json()["detail"], code


def test_main_process_never_runs_pasted_code(client, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("pasted code reached the in-process runner")
    body = create(client).json()  # real generation, in the child
    rows = rows_of(body)
    monkeypatch.setattr(V, "run_program", boom)
    monkeypatch.setattr(V, "diagnose", boom)
    body2 = create(client, LOOP + "\nprint(total + 1)")
    assert body2.status_code == 200
    assert client.get(f"/api/custom/sets/{body['id']}").status_code == 200
    for row in rows.values():
        assert client.post(f"/api/puzzle/{row['id']}/answer", json=correct_body(row)).json()["correct"] is True
        assert client.post(f"/api/puzzle/{row['id']}/answer", json=wrong_body(row)).json()["correct"] is False
        assert client.post(f"/api/puzzle/{row['id']}/explain", json=wrong_body(row)).status_code == 200
        assert client.get(f"/api/puzzle/{row['id']}/hint", params={"level": 2}).status_code == 200
    with pytest.raises(RuntimeError):  # the executing half refuses to run outside the worker
        custom_gen.generate(LOOP)


def test_busy_sandbox_answers_429(client, monkeypatch):
    monkeypatch.setattr(sandbox, "_slots", threading.BoundedSemaphore(1))
    monkeypatch.setattr(sandbox, "BUSY_WAIT_S", 0.2)
    assert sandbox._slots.acquire(timeout=1)
    r = create(client)
    assert r.status_code == 429 and "bận" in r.json()["detail"]


def test_child_environment_is_scrubbed(monkeypatch):
    monkeypatch.setenv("SYNTAX_STACK_TUTOR_TOKEN", "secret-token")
    env = sandbox._child_env()
    assert "SYNTAX_STACK_TUTOR_TOKEN" not in env and "secret-token" not in json.dumps(env)


def test_worker_limits_use_the_expected_rlimits():
    class FakeResource:
        RLIM_INFINITY = -1
        RLIMIT_AS, RLIMIT_CPU, RLIMIT_FSIZE, RLIMIT_NPROC, RLIMIT_NOFILE, RLIMIT_CORE = range(6)

        def __init__(self):
            self.set = {}

        def getrlimit(self, which):
            return (-1, -1)

        def setrlimit(self, which, pair):
            self.set[which] = pair

    from app import sandbox_worker as w
    fake = FakeResource()
    applied = w.apply_limits(fake)
    assert fake.set[fake.RLIMIT_AS] == (256 * 1024 * 1024, 256 * 1024 * 1024)
    assert fake.set[fake.RLIMIT_CPU] == (3, 4)
    assert fake.set[fake.RLIMIT_NPROC] == (0, 0)
    assert fake.set[fake.RLIMIT_FSIZE][0] == 1024 * 1024 and fake.set[fake.RLIMIT_CORE] == (0, 0)
    assert set(applied) == {"AS", "CPU", "FSIZE", "NPROC", "NOFILE", "CORE"} and all(applied.values())

    class Lower(FakeResource):
        def getrlimit(self, which):
            return (10, 10)  # the environment already allows less: limits are never raised

    low = Lower()
    w.apply_limits(low)
    assert all(soft <= 10 and hard <= 10 for soft, hard in low.set.values())


def test_worker_round_trip_runs_a_diagnose_job():
    r = sandbox.run_job({"op": "diagnose", "code": LOOP, "expected": "10"}, 5)
    assert r["passed"] is True and r["run_ok"] is True


def test_generation_is_deterministic_for_the_same_code(client):
    a = create(client).json()
    b = create(client).json()
    assert a["id"] != b["id"]
    # stored rows (not the per-id shuffled public views) are identical apart from their ids
    strip = lambda body: [{k: v for k, v in r.items() if k != "id"} for r in rows_of(body).values()]
    assert strip(a) == strip(b)


def test_offline_generator_still_uses_the_shared_helpers():
    import importlib.util
    from tests.conftest import BACKEND
    spec = importlib.util.spec_from_file_location("generate_bank_shared", BACKEND / "scripts" / "generate_bank.py")
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    from app import puzzle_tools
    assert gen.mutations is puzzle_tools.mutations and gen.build_bug_form is puzzle_tools.build_bug_form
    assert gen.Drop is puzzle_tools.Drop and gen.place_options is puzzle_tools.place_options
