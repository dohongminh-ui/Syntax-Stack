import json

import pytest

from app import rows as R

LEVELS = ["r1", "r2", "r3", "r4", "r5"]


def run(client, lid, rows):
    return client.post(f"/api/rows/levels/{lid}/run", json={"rows": rows})


def canon(lid):
    return R.canonical_rows(R.get_level(lid))


def swap(lid, old, new):
    """Canonical rows with token id ``old`` replaced by ``new``."""
    rows = canon(lid)
    hit = False
    for r in rows:
        for t in r["tokens"]:
            if t["id"] == old:
                t["id"], hit = new, True
    assert hit
    return rows


def place(*rows):
    """place([(row, indent, [ids])...]) -> payload with tokens packed from the indent column."""
    lv = None
    out = []
    for ridx, col, ids, lid in rows:
        lv = R.get_level(lid)
        toks = []
        for tid in ids:
            toks.append({"id": tid, "col": col})
            col += lv["_tokens"][tid]["w"]
        out.append({"row": ridx, "tokens": toks})
    return out


# ------------------------------------------------------------------ levels listing / GET


def test_levels_listing(client):
    j = client.get("/api/rows/levels").json()
    assert [l["id"] for l in j] == LEVELS
    assert set(j[0]) == {"id", "order", "title", "concept", "rows", "cols"}
    assert [l["concept"] for l in j] == ["variables", "conditions", "loops", "loops", "functions"]
    assert j[0]["title"] == "Biến đầu tiên" and all(l["cols"] == 10 for l in j)


@pytest.mark.parametrize("lid", LEVELS)
def test_get_level_never_leaks(client, lid):
    r = client.get(f"/api/rows/levels/{lid}")
    assert r.status_code == 200
    j = r.json()
    for word in ("solution", "is_distractor", "required_constructs", "group_hints", "hints", "canonical"):
        assert word not in r.text
    assert j["id"] == lid and j["cols"] == 10 and j["indent_cols"] == 2 and j["expected_output"]
    assert all(set(t) == {"id", "text", "w", "topic"} for t in j["tokens"])
    assert all(1 <= t["w"] <= 3 for t in j["tokens"])
    assert len({t["id"] for t in j["tokens"]}) == len(j["tokens"])
    assert all(t["topic"] in {"syntax", "variables", "conditions", "loops", "functions"} for t in j["tokens"])
    # tokens are not listed with the distractors last
    lv = R.get_level(lid)
    flags = [t["is_distractor"] for t in lv["tokens"]]
    assert flags != sorted(flags)


def test_get_level_404(client):
    assert client.get("/api/rows/levels/r99").status_code == 404
    assert run(client, "r99", []).status_code == 404
    assert client.get("/api/rows/levels/r99/hint", params={"level": 1}).status_code == 404


def test_level_content_matches_spec(client):
    texts = {lid: sorted(t["text"] for t in R.get_level(lid)["tokens"]) for lid in LEVELS}
    assert texts["r1"] == sorted(["diem", "=", "7", "print(diem)", "8", 'print("diem")'])
    assert "print(\"Trượt\")" in texts["r2"] and "<" in texts["r2"] and texts["r2"].count("=") == 2
    assert {"range(2)", "range(3)", "range(4)", "while"} <= set(texts["r3"])
    assert texts["r4"].count("print(tong)") == 2 and "range(1, 3)" in texts["r4"]
    assert {"+", "print(x * 2)", "return", "def"} <= set(texts["r5"])
    for lid in LEVELS:
        lv = R.get_level(lid)
        assert 4 <= lv["rows"] <= 7
        distractors = sum(1 for t in lv["tokens"] if t["is_distractor"])
        assert 2 <= distractors <= 4
        for row in lv["solution"]:
            width = row["indent"] + sum(lv["_tokens"][t]["w"] for t in row["tokens"])
            assert width <= lv["cols"]


# ------------------------------------------------------------------ canonical + distractors


@pytest.mark.parametrize("lid", LEVELS)
def test_canonical_solution_passes(client, lid):
    r = run(client, lid, canon(lid))
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["passed"] is True and j["error_group"] is None and j["row"] is None
    lv = R.get_level(lid)
    assert j["unused_distractors"] == sum(1 for t in lv["tokens"] if t["is_distractor"])
    assert j["actual_output"] == lv["expected_output"] == j["expected_output"]


def test_passing_run_utf8(client):
    r = run(client, "r2", canon("r2"))
    assert r.json()["actual_output"] == "Đậu"
    assert "Đậu" in r.content.decode("utf-8")


DISTRACTOR_CASES = [
    # (level, token to replace, replacement, expected group, expected board row)
    ("r1", "t5", "t3", "output_mismatch", 0),     # diem = 8
    ("r1", "t2", "t6", "output_mismatch", 1),     # print("diem")
    ("r2", "t1", "t4", "output_mismatch", 1),     # if diem < 5
    ("r2", "t2", "t8", "output_mismatch", 2),     # print("Trượt")
    ("r3", "t4", "t1", "output_mismatch", 0),     # range(2)
    ("r3", "t4", "t9", "output_mismatch", 0),     # range(4)
    ("r4", "t10", "t2", "output_mismatch", 1),    # range(1, 3)
    ("r5", "t5", "t7", "output_mismatch", 1),     # return x + 2
]


@pytest.mark.parametrize("lid,old,new,group,row", DISTRACTOR_CASES)
def test_distractor_swap_fails(client, lid, old, new, group, row):
    j = run(client, lid, swap(lid, old, new)).json()
    assert j["passed"] is False
    assert j["error_group"] == group, j
    assert j["row"] == row, j
    assert j["unused_distractors"] is None and j["message"]


def test_level3_range2_spec_case(client):
    j = run(client, "r3", swap("r3", "t4", "t1")).json()
    assert j["error_group"] == "output_mismatch" and j["row"] == 0
    assert j["actual_output"] == "0\n1" and j["expected_output"] == "0\n1\n2"
    assert j["code"] == "for i in range(2) :\n    print(i)"
    assert "0, 1" in j["message"] and "0, 1, 2" in j["message"]


@pytest.mark.parametrize("length", [2, 3])
def test_loop_trace_shows_executed_rows_variables_and_output(client, length):
    attempt = swap("r3", "t4", "t1") if length == 2 else canon("r3")
    attempt[0]["row"], attempt[1]["row"] = 1, 3
    baseline = run(client, "r3", attempt).json()
    assert "trace" not in baseline
    response = client.post("/api/rows/levels/r3/run", json={"rows": attempt, "trace": True}).json()
    trace = response.pop("trace")
    assert response == baseline
    assert response["passed"] == (length == 3)
    assert not trace["truncated"]
    assert [step["row"] for step in trace["steps"]] == [1, 3] * length + [1]
    prints = [step for step in trace["steps"] if step["row"] == 3]
    assert [step["bindings"] for step in prints] == [{"i": str(i)} for i in range(length)]
    assert [step["output"].splitlines() for step in prints] == [
        [str(j) for j in range(i + 1)] for i in range(length)
    ]


def test_trace_identifies_function_scope_and_empty_compile_trace(client):
    response = client.post("/api/rows/levels/r5/run", json={"rows": canon("r5"), "trace": True}).json()
    steps = response["trace"]["steps"]
    calls = [step for step in steps if step["scope"] == "gap_doi"]
    assert len(calls) == 1
    assert calls[0]["bindings"] == {"x": "4"}
    assert calls[0]["output"] == "" and steps[-1]["output"] == "8\n"
    attempt = canon("r3")
    attempt[0]["tokens"].pop()
    invalid = client.post("/api/rows/levels/r3/run", json={"rows": attempt, "trace": True}).json()
    assert invalid["error_group"] == "missing_colon"
    assert invalid["trace"] == {"steps": [], "truncated": False}


def test_while_distractor_fails_on_its_row(client):
    # while i in range(3) : -> `i` is never created, Python reports an error on that row
    rows = place((0, 0, ["t6", "t7", "t8", "t4", "t5"], "r3"), (1, 1, ["t3"], "r3"))
    j = run(client, "r3", rows).json()
    assert j["passed"] is False and j["row"] == 0 and j["error_group"] == "syntax"
    assert "'i'" in j["message"]


def test_level4_print_indented_into_loop_spec_case(client):
    rows = canon("r4")
    rows[3]["tokens"] = [{"id": "t7", "col": 1}]  # print(tong) indented one level
    j = run(client, "r4", rows).json()
    assert j["passed"] is False and j["error_group"] == "output_mismatch" and j["row"] == 3
    assert j["actual_output"] == "1\n3\n6"
    assert j["code"].endswith("    print(tong)")


def test_level4_second_print_is_an_extra_line(client):
    rows = canon("r4") + [{"row": 4, "tokens": [{"id": "t16", "col": 0}]}]
    j = run(client, "r4", rows).json()
    assert j["error_group"] == "output_mismatch" and j["row"] == 4 and j["actual_output"] == "6\n6"


def test_distractor_print_in_function_misses_return(client):
    rows = canon("r5")
    rows[1]["tokens"] = [{"id": "t3", "col": 1}]  # print(x * 2) instead of return x * 2
    j = run(client, "r5", rows).json()
    assert j["passed"] is False and j["error_group"] == "missing_construct" and j["row"] is None


def test_any_correct_program_is_accepted_not_only_canonical(client):
    # r2: the two `diem` tokens and the two `=` tokens are interchangeable
    rows = swap("r2", "t3", "t9")
    for r in rows:
        for t in r["tokens"]:
            if t["id"] == "t9" and r["row"] == 1:
                t["id"] = "t3"
    j = run(client, "r2", rows).json()
    assert j["passed"] is True
    # r4: the distractor print(tong) in the right place is fine, but then the canonical one is "unused"
    j = run(client, "r4", swap("r4", "t7", "t16")).json()
    assert j["passed"] is True and j["unused_distractors"] == 2
    # extra gaps between tokens do not matter
    rows = canon("r3")
    rows[0]["tokens"] = [{"id": "t2", "col": 0}, {"id": "t7", "col": 2}, {"id": "t8", "col": 4},
                         {"id": "t4", "col": 5}, {"id": "t5", "col": 9}]
    assert run(client, "r3", rows).json()["passed"] is True
    # rows need not start at board row 0 and empty rows are skipped
    rows = canon("r3")
    rows[0]["row"], rows[1]["row"] = 1, 3
    assert run(client, "r3", rows + [{"row": 0, "tokens": []}]).json()["passed"] is True


# ------------------------------------------------------------------ error groups


def test_empty(client):
    for payload in ([], [{"row": 0, "tokens": []}, {"row": 2, "tokens": []}]):
        j = run(client, "r1", payload).json()
        assert j["passed"] is False and j["error_group"] == "empty" and j["row"] is None


def test_missing_colon(client):
    rows = canon("r3")
    rows[0]["tokens"] = [t for t in rows[0]["tokens"] if t["id"] != "t5"]
    j = run(client, "r3", rows).json()
    assert j["error_group"] == "missing_colon" and j["row"] == 0 and j["passed"] is False
    rows = canon("r5")
    rows[0]["tokens"] = [t for t in rows[0]["tokens"] if t["id"] != "t8"]
    j = run(client, "r5", rows).json()
    assert j["error_group"] == "missing_colon" and j["row"] == 0


def test_bad_indent(client):
    rows = canon("r3")
    rows[1]["tokens"] = [{"id": "t3", "col": 0}]  # body not indented
    j = run(client, "r3", rows).json()
    assert j["error_group"] == "bad_indent" and j["row"] == 1
    rows = canon("r1")
    rows[1]["tokens"] = [{"id": "t2", "col": 1}]  # unexpected indent
    j = run(client, "r1", rows).json()
    assert j["error_group"] == "bad_indent" and j["row"] == 1


def test_syntax_error_row(client):
    # r2: stray extra `=` in the if line
    rows = place((0, 0, ["t3", "t10", "t6"], "r2"), (1, 0, ["t5", "t9", "t1", "t12", "t11", "t7"], "r2"),
                 (2, 1, ["t2"], "r2"))
    j = run(client, "r2", rows).json()
    assert j["error_group"] == "syntax" and j["row"] == 1


def test_wrong_order(client):
    rows = canon("r4")
    rows[0]["row"], rows[3]["row"] = 3, 0  # print(tong) first, tong = 0 last
    j = run(client, "r4", rows).json()
    assert j["error_group"] == "wrong_order" and j["row"] == 0 and j["passed"] is False
    # same lines, same indents, only reordered but no error -> wrong_order too
    rows = canon("r1")
    rows[0]["row"], rows[1]["row"] = 1, 0
    assert run(client, "r1", rows).json()["error_group"] == "wrong_order"


def test_missing_construct(client):
    rows = place((0, 0, ["t3", "t10", "t6"], "r2"), (1, 0, ["t2"], "r2"))  # diem = 8 / print("Đậu") without if
    j = run(client, "r2", rows).json()
    assert j["passed"] is False and j["error_group"] == "missing_construct" and j["row"] is None
    assert "if" in j["message"]


# ------------------------------------------------------------------ 422s


def test_422_cases(client):
    c = canon("r3")
    cases = {
        "duplicate id": [{"row": 0, "tokens": [{"id": "t2", "col": 0}, {"id": "t2", "col": 2}]}],
        "unknown id": [{"row": 0, "tokens": [{"id": "t99", "col": 0}]}],
        "overlap": [{"row": 0, "tokens": [{"id": "t4", "col": 0}, {"id": "t2", "col": 2}]}],
        "overflow": [{"row": 0, "tokens": [{"id": "t4", "col": 8}]}],
        "negative col": [{"row": 0, "tokens": [{"id": "t2", "col": -1}]}],
        "first col too far": [{"row": 0, "tokens": [{"id": "t2", "col": 3}]}],
        "row out of range": [{"row": 4, "tokens": [{"id": "t2", "col": 0}]}],
        "negative row": [{"row": -1, "tokens": [{"id": "t2", "col": 0}]}],
        "duplicate row": [{"row": 0, "tokens": [{"id": "t2", "col": 0}]}, {"row": 0, "tokens": [{"id": "t7", "col": 0}]}],
        "id reused across rows": [{"row": 0, "tokens": [{"id": "t2", "col": 0}]}, {"row": 1, "tokens": [{"id": "t2", "col": 0}]}],
    }
    for name, rows in cases.items():
        r = run(client, "r3", rows)
        assert r.status_code == 422, name
        assert "detail" in r.json(), name
    assert client.post("/api/rows/levels/r3/run", json={"rows": "x"}).status_code == 422
    assert client.post("/api/rows/levels/r3/run", json={"rows": [{"row": "a", "tokens": []}]}).status_code == 422
    assert client.post("/api/rows/levels/r3/run", content="nope",
                       headers={"content-type": "application/json"}).status_code == 422
    assert run(client, "r3", c).status_code == 200


def test_unsafe_input_cannot_be_built_from_tokens(client):
    # whatever the player places is only ever bank tokens; spot-check a nonsense board still returns cleanly
    rows = [{"row": 0, "tokens": [{"id": "t6", "col": 0}, {"id": "t1", "col": 2}, {"id": "t9", "col": 5}]}]
    j = run(client, "r3", rows).json()
    assert j["passed"] is False


# ------------------------------------------------------------------ hints


def test_hints_general_and_per_group(client):
    lv = R.get_level("r3")
    for level in (1, 2, 3):
        j = client.get("/api/rows/levels/r3/hint", params={"level": level}).json()
        assert j == {"level": level, "text": lv["hints"][level - 1], "source": "canned"}
        j = client.get("/api/rows/levels/r3/hint", params={"level": level, "error_group": "output_mismatch"}).json()
        assert j["text"] == lv["group_hints"]["output_mismatch"][level - 1]
        assert j["level"] == level and j["source"] == "canned"
    j1 = client.get("/api/rows/levels/r3/hint", params={"level": 1}).json()
    j2 = client.get("/api/rows/levels/r3/hint", params={"level": 1, "error_group": "output_mismatch"}).json()
    assert j1["text"] != j2["text"]
    assert "range()" in client.get("/api/rows/levels/r3/hint", params={"level": 1, "error_group": "output_mismatch"}).json()["text"]


def test_hint_groups_fall_back_to_generic(client):
    for g in ("syntax", "empty", "missing_colon", "bad_indent", "wrong_order", "missing_construct"):
        for lid in LEVELS:
            for level in (1, 2, 3):
                r = client.get(f"/api/rows/levels/{lid}/hint", params={"level": level, "error_group": g})
                assert r.status_code == 200 and r.json()["text"], (lid, g, level)


def test_hint_validation(client):
    assert client.get("/api/rows/levels/r3/hint", params={"level": 4}).status_code == 422
    assert client.get("/api/rows/levels/r3/hint", params={"level": 0}).status_code == 422
    assert client.get("/api/rows/levels/r3/hint").status_code == 422
    assert client.get("/api/rows/levels/r3/hint", params={"level": 1, "error_group": "nope"}).status_code == 422


def test_all_levels_have_three_hints_and_group_hints():
    for lid in LEVELS:
        lv = R.get_level(lid)
        assert len(lv["hints"]) == 3
        for g, hs in lv["group_hints"].items():
            assert len(hs) == 3, (lid, g)
        assert {"output_mismatch", "wrong_order", "bad_indent", "missing_construct"} <= set(lv["group_hints"])
