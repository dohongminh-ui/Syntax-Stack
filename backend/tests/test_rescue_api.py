import pytest

from app import bank

TOPICS = ["variables", "conditions", "loops", "functions"]


def nxt(client, **kw):
    body = {"topic": "loops", "tier": 1, "level": "intermediate", "kind": "rescue"}
    body.update(kw)
    return client.post("/api/puzzle/next", json=body)


def correct_body(row, reveal=True):
    d, typ = row["data"], row["type"]
    if typ in ("fill_blank", "predict_output"):
        return {"option_id": next(o["id"] for o in d["options"] if o["correct"]), "reveal": reveal}
    if typ == "find_bug":
        return {"option_id": next(o["id"] for o in d["options"] if o["correct"]), "reveal": reveal}
    return {"order": [{"line_id": s["line_id"], "indent": s["indent"]} for s in d["solution"]], "reveal": reveal}


def wrong_body(row, reveal=True):
    d, typ = row["data"], row["type"]
    if typ in ("fill_blank", "predict_output"):
        return {"option_id": next(o["id"] for o in d["options"] if not o["correct"]), "reveal": reveal}
    if typ == "find_bug":
        return {"option_id": next(o["id"] for o in d["options"] if not o["correct"]), "reveal": reveal}
    ids = [l["id"] for l in d["lines"]]
    return {"order": [{"line_id": i, "indent": 0} for i in ids], "reveal": reveal}


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    j = r.json()
    assert j["ok"] is True and j["puzzles"] >= 500


def test_next_reaches_all_four_types_and_never_leaks(client):
    seen = set()
    for topic in TOPICS:
        for tier in (1, 2, 3):
            for level in ("beginner", "advanced"):
                for _ in range(25):
                    r = nxt(client, topic=topic, tier=tier, level=level)
                    assert r.status_code == 200, r.text
                    p = r.json()
                    seen.add(p["type"])
                    assert p["topic"] == topic and p["tier"] == tier
                    assert set(p) == {"id", "template_id", "topic", "type", "tier", "prompt", "code",
                                      "expected_output", "lines", "options"}
                    text = r.text
                    for word in ("solution", "correct", "explanation", "bug_line", "hints"):
                        assert word not in text, (word, text)
                    if p["type"] == "fill_blank":
                        assert p["code"].count("___") == 1 and p["expected_output"]
                    if p["type"] == "predict_output":
                        assert p["expected_output"] is None and p["options"]
                    if p["type"] == "parsons":
                        assert p["code"] is None and p["options"] is None and p["lines"]
                        assert all("indent" not in l for l in p["lines"])
                    if p["type"] == "find_bug":
                        assert p["lines"] and all("indent" in l for l in p["lines"]) and p["options"]
    assert seen == {"parsons", "fill_blank", "predict_output", "find_bug"}


def test_option_count_by_level(client):
    for _ in range(30):
        b = nxt(client, level="beginner", topic="conditions", tier=2).json()
        i = nxt(client, level="intermediate", topic="conditions", tier=2).json()
        a = nxt(client, level="advanced", topic="conditions", tier=2).json()
        if b["options"]:
            assert len(b["options"]) == 3
        if i["options"]:
            assert len(i["options"]) == 4
        if a["options"]:
            assert len(a["options"]) == 4


def test_exclusions(client):
    first = nxt(client).json()
    for _ in range(15):
        again = nxt(client, exclude_ids=[first["id"]]).json()
        assert again["id"] != first["id"]
    # soft template preference: another template is chosen when available
    for _ in range(15):
        other = nxt(client, exclude_templates=[first["template_id"]]).json()
        assert other["template_id"] != first["template_id"]
    # ...but ignored when it would leave nothing
    all_templates = {nxt(client, topic="loops", tier=1).json()["template_id"] for _ in range(60)}
    r = nxt(client, exclude_templates=sorted(all_templates))
    assert r.status_code == 200


def test_exclude_all_ids_gives_404(client, all_rows):
    ids = [r["id"] for r in all_rows if r["topic"] == "loops" and r["tier"] == 1 and not r["debug_only"]]
    r = nxt(client, exclude_ids=ids)
    assert r.status_code == 404 and "detail" in r.json()


def test_next_validation(client):
    assert client.post("/api/puzzle/next", json={"kind": "rescue", "level": "beginner"}).status_code == 422
    assert client.post("/api/puzzle/next", json={"kind": "debug", "level": "beginner"}).status_code == 422
    assert nxt(client, topic="cooking").status_code == 422
    assert nxt(client, tier=9).status_code == 422
    assert nxt(client, level="expert").status_code == 422
    assert client.post("/api/puzzle/next", content="not json",
                       headers={"content-type": "application/json"}).status_code == 422


@pytest.mark.parametrize("typ", ["fill_blank", "predict_output", "parsons", "find_bug"])
def test_answer_correct_and_incorrect(client, all_rows, typ):
    rows = [r for r in all_rows if r["type"] == typ and not r["debug_only"]][:12]
    assert rows
    for row in rows:
        ok = client.post(f"/api/puzzle/{row['id']}/answer", json=correct_body(row))
        assert ok.status_code == 200, ok.text
        j = ok.json()
        assert j["correct"] is True and j["error_group"] is None
        assert j["solution_code"] == row["solution_code"] and j["explanation"]
        assert set(j) == {"correct", "error_group", "message", "actual_output", "solution_code", "explanation"}

        bad = client.post(f"/api/puzzle/{row['id']}/answer", json=wrong_body(row))
        assert bad.status_code == 200, bad.text
        j = bad.json()
        assert j["correct"] is False
        assert j["error_group"] in {"wrong_order", "bad_indent", "syntax", "output_mismatch", "wrong_line",
                                    "wrong_fix", "wrong_choice"}
        assert j["message"]
        assert j["solution_code"] == row["solution_code"] and j["explanation"]


@pytest.mark.parametrize("typ", ["fill_blank", "predict_output", "parsons", "find_bug"])
def test_reveal_false_hides_solution_when_wrong(client, all_rows, typ):
    row = next(r for r in all_rows if r["type"] == typ and not r["debug_only"])
    j = client.post(f"/api/puzzle/{row['id']}/answer", json=wrong_body(row, reveal=False)).json()
    assert j["correct"] is False
    assert j["solution_code"] is None and j["explanation"] is None
    if typ == "predict_output":
        assert j["actual_output"] is None
        assert row["expected_output"] not in j["message"]
    # reveal defaults to false when omitted
    body = wrong_body(row)
    body.pop("reveal")
    assert client.post(f"/api/puzzle/{row['id']}/answer", json=body).json()["solution_code"] is None
    # a correct answer always carries the solution
    j = client.post(f"/api/puzzle/{row['id']}/answer", json=correct_body(row, reveal=False)).json()
    assert j["correct"] is True and j["solution_code"]


def test_fill_blank_wrong_message_has_actual_vs_expected(client, all_rows):
    row = next(r for r in all_rows if r["template_id"] == "loops_range_fill" and r["tier"] == 1)
    wrong = next(o for o in row["data"]["options"] if not o["correct"] and o["actual_output"])
    j = client.post(f"/api/puzzle/{row['id']}/answer", json={"option_id": wrong["id"], "reveal": True}).json()
    assert j["error_group"] == "output_mismatch" and j["actual_output"] == wrong["actual_output"]
    assert "Đầu ra không khớp" in j["message"]


def test_find_bug_wrong_line_and_wrong_fix(client, all_rows):
    seen = set()
    for row in [r for r in all_rows if r["type"] == "find_bug"][:80]:
        d = row["data"]
        for o in d["options"]:
            if o["correct"]:
                continue
            j = client.post(f"/api/puzzle/{row['id']}/answer", json={"option_id": o["id"], "reveal": True}).json()
            assert j["correct"] is False
            expected = "wrong_fix" if o["line_id"] == d["bug_line"] else "wrong_line"
            assert j["error_group"] == expected
            seen.add(expected)
    assert seen == {"wrong_line", "wrong_fix"}
    # a line_id in the body is ignored
    row = next(r for r in all_rows if r["type"] == "find_bug")
    good = next(o["id"] for o in row["data"]["options"] if o["correct"])
    j = client.post(f"/api/puzzle/{row['id']}/answer", json={"option_id": good, "line_id": "l99", "reveal": True}).json()
    assert j["correct"] is True


def test_find_bug_next_exposes_line_tied_options(client):
    for level in ("beginner", "intermediate"):
        for _ in range(40):
            p = client.post("/api/puzzle/next", json={"kind": "debug", "template_id": "loops_range_fill",
                                                      "level": level}).json()
            assert p["type"] == "find_bug"
            line_ids = {l["id"] for l in p["lines"]}
            assert all(set(o) == {"id", "line_id", "text"} and o["line_id"] in line_ids for o in p["options"])
            assert len({o["line_id"] for o in p["options"]}) >= 2
            assert len(p["options"]) == (3 if level == "beginner" else 4)


def test_parsons_error_groups(client, all_rows):
    row = next(r for r in all_rows if r["template_id"] == "loops_body_parsons" and r["tier"] == 1)
    d = row["data"]
    sol = d["solution"]
    # right order, wrong indentation -> bad_indent
    flat = [{"line_id": s["line_id"], "indent": 0} for s in sol]
    j = client.post(f"/api/puzzle/{row['id']}/answer", json={"order": flat, "reveal": True}).json()
    assert j["correct"] is False and j["error_group"] == "bad_indent"
    # reversed order -> wrong_order (or a syntax-level error); never "correct"
    rev = [dict(s) for s in reversed(sol)]
    j = client.post(f"/api/puzzle/{row['id']}/answer", json={"order": rev, "reveal": True}).json()
    assert j["correct"] is False and j["error_group"] in {"wrong_order", "bad_indent"}


def test_answer_validation_and_404(client, all_rows):
    assert client.post("/api/puzzle/nope__001/answer", json={"option_id": "a"}).status_code == 404
    fb = next(r for r in all_rows if r["type"] == "fill_blank" and not r["debug_only"])
    assert client.post(f"/api/puzzle/{fb['id']}/answer", json={}).status_code == 422
    assert client.post(f"/api/puzzle/{fb['id']}/answer", json={"option_id": "z"}).status_code == 422
    ps = next(r for r in all_rows if r["type"] == "parsons" and not r["debug_only"])
    ids = [l["id"] for l in ps["data"]["lines"]]
    assert client.post(f"/api/puzzle/{ps['id']}/answer", json={"order": [{"line_id": ids[0], "indent": 0}]}).status_code == 422
    too_deep = [{"line_id": i, "indent": 3} for i in ids]
    assert client.post(f"/api/puzzle/{ps['id']}/answer", json={"order": too_deep}).status_code == 422
    dup = [{"line_id": ids[0], "indent": 0}] * len(ids)
    assert client.post(f"/api/puzzle/{ps['id']}/answer", json={"order": dup}).status_code == 422
    bug = next(r for r in all_rows if r["type"] == "find_bug" and not r["debug_only"])
    assert client.post(f"/api/puzzle/{bug['id']}/answer", json={"option_id": "z"}).status_code == 422
    assert client.post(f"/api/puzzle/{bug['id']}/answer", json={"line_id": "l1"}).status_code == 422


def test_hints(client, all_rows):
    row = all_rows[0]
    texts = []
    for level in (1, 2, 3):
        r = client.get(f"/api/puzzle/{row['id']}/hint", params={"level": level})
        assert r.status_code == 200
        j = r.json()
        assert j["level"] == level and j["source"] == "canned" and j["text"]
        texts.append(j["text"])
    assert texts == row["hints"]
    assert client.get(f"/api/puzzle/{row['id']}/hint", params={"level": 4}).status_code == 422
    assert client.get(f"/api/puzzle/{row['id']}/hint").status_code == 422
    assert client.get("/api/puzzle/nope__001/hint", params={"level": 1}).status_code == 404


def test_hints_do_not_give_the_answer(all_rows):
    for r in all_rows:
        if r["type"] == "fill_blank" and not r["debug_only"]:
            correct = next(o["text"] for o in r["data"]["options"] if o["correct"])
            if len(correct) >= 4:
                assert not any(f"điền {correct}" in h.lower() for h in r["hints"])


def test_debug_returns_same_template_different_variant(client, all_rows):
    # fill_blank family has a find_bug form
    row = next(r for r in all_rows if r["template_id"] == "loops_range_fill" and not r["debug_only"])
    seen = set()
    for _ in range(20):
        j = nxt(client, kind="debug", template_id=row["template_id"], exclude_ids=[row["id"]], topic=None, tier=None).json()
        assert j["template_id"] == row["template_id"] and j["id"] != row["id"]
        assert j["type"] == "find_bug" and j["lines"] and j["options"]
        seen.add(j["id"])
    assert len(seen) > 1
    # a find_bug template debugs into find_bug
    j = nxt(client, kind="debug", template_id="loops_bug", exclude_ids=[]).json()
    assert j["template_id"] == "loops_bug" and j["type"] == "find_bug"
    # templates without a find_bug form keep their own type
    j = nxt(client, kind="debug", template_id="variables_order_parsons").json()
    assert j["template_id"] == "variables_order_parsons" and j["type"] == "parsons"
    j = nxt(client, kind="debug", template_id="loops_sum_predict").json()
    assert j["type"] == "predict_output"
    # debug-only forms are never served as normal puzzles
    for _ in range(40):
        p = nxt(client, topic="loops", tier=1).json()
        assert "__d" not in p["id"]


def test_debug_puzzle_is_answerable(client, all_rows):
    j = nxt(client, kind="debug", template_id="functions_return_fill").json()
    row = bank.get_puzzle(j["id"])
    assert client.post(f"/api/puzzle/{j['id']}/answer", json=correct_body(row)).json()["correct"] is True


def test_debug_errors(client):
    assert nxt(client, kind="debug", template_id="no_such_template").status_code == 404
    ids = [f"loops_bug__{i:03d}" for i in range(1, 80)]
    assert nxt(client, kind="debug", template_id="loops_bug", exclude_ids=ids).status_code == 404


def test_last_commit_defaults_to_tier_3(client):
    r = client.post("/api/puzzle/next", json={"kind": "last_commit", "level": "intermediate"})
    assert r.status_code == 200 and r.json()["tier"] == 3


def test_cors_headers(client):
    r = client.options("/api/health", headers={"Origin": "http://localhost:5173",
                                               "Access-Control-Request-Method": "GET"})
    assert r.headers.get("access-control-allow-origin") == "http://localhost:5173"
    r = client.get("/api/health", headers={"Origin": "http://127.0.0.1:8080"})
    assert r.headers.get("access-control-allow-origin") == "http://127.0.0.1:8080"
    r = client.get("/api/health", headers={"Origin": "http://evil.example.com"})
    assert "access-control-allow-origin" not in r.headers
