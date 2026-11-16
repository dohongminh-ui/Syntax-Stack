"""Every stored puzzle is re-verified with the validator: solution passes, every distractor fails."""
import json

from app import bank
from app import validator as V

TOPICS = {"variables", "conditions", "loops", "functions"}
TYPES = {"parsons", "fill_blank", "predict_output", "find_bug"}


def _fixed_lines(data):
    return [(l["indent"], l["text"]) for l in data["lines"]]


def _join(items):
    return "\n".join("    " * i + t for i, t in items)


def test_bank_shape(all_rows):
    primary = [r for r in all_rows if not r["debug_only"]]
    assert len(primary) >= 500
    assert {r["topic"] for r in primary} == TOPICS
    assert {r["type"] for r in primary} == TYPES
    assert len({r["template_id"] for r in primary}) == 16
    assert len({r["id"] for r in all_rows}) == len(all_rows)
    for t in {r["template_id"] for r in primary}:
        assert sum(1 for r in primary if r["template_id"] == t) >= 20
    for topic in TOPICS:
        for tier in (1, 2, 3):
            assert sum(1 for r in primary if r["topic"] == topic and r["tier"] == tier) >= 20


def test_every_puzzle_is_consistent(all_rows):
    for r in all_rows:
        d = r["data"]
        assert len(r["hints"]) == 3 and all(r["hints"]), r["id"]
        assert r["prompt"] and r["explanation"], r["id"]
        assert "{" not in r["prompt"] + r["explanation"] + "".join(r["hints"]), r["id"]
        out = r["expected_output"]
        assert out and len(out.split("\n")) <= 5 and all(len(l) <= 40 for l in out.split("\n")), r["id"]
        prog = [l for l in r["solution_code"].split("\n") if l.strip()]
        assert 2 <= len(prog) <= 7, r["id"]
        if "options" in d:
            opts = d["options"]
            assert [o["id"] for o in opts] == list("abcd"[:len(opts)])
            assert sum(1 for o in opts if o["correct"]) == 1, r["id"]
            correct_idx = next(i for i, o in enumerate(opts) if o["correct"])
            assert correct_idx <= 2, "correct option must survive trimming to 3 options"
            assert len({o["text"] for o in opts}) == len(opts), r["id"]
            if not r["debug_only"]:
                assert len(opts) == 4, r["id"]
        if r["tier"] == 3:
            assert "for " in r["solution_code"], r["id"]  # nesting: a block inside a loop


def test_solutions_pass_and_distractors_fail(all_rows):
    for r in all_rows:
        d, exp, typ = r["data"], r["expected_output"], r["type"]
        assert V.diagnose(r["solution_code"], exp).passed, r["id"]
        if typ == "fill_blank":
            for o in d["options"]:
                prog = r["code"].replace("___", o["text"])
                assert V.diagnose(prog, exp).passed == o["correct"], (r["id"], o["text"])
        elif typ == "predict_output":
            assert V.normalize_output(V.run_program(r["code"]).output) == exp
            texts = [o["text"] for o in d["options"]]
            assert len(set(texts)) == len(texts)
            for o in d["options"]:
                assert (o["text"] == exp) == o["correct"], r["id"]
        elif typ == "parsons":
            texts = {l["id"]: l["text"] for l in d["lines"]}
            sol = "\n".join("    " * s["indent"] + texts[s["line_id"]] for s in d["solution"])
            assert V.diagnose(sol, exp).passed, r["id"]
            shuffled = "\n".join(l["text"] for l in d["lines"])
            assert not V.diagnose(shuffled, exp).passed, f"{r['id']}: shuffle already correct"
            assert [s["line_id"] for s in d["solution"]] != [l["id"] for l in d["lines"]]
            assert d["distractors"], r["id"]
            for dd in d["distractors"]:
                assert not V.diagnose(dd["code"], exp).passed, (r["id"], dd["name"])
        elif typ == "find_bug":
            items = _fixed_lines(d)
            bug = int(d["bug_line"][1:]) - 1
            assert not V.diagnose(_join(items), exp).passed, f"{r['id']}: buggy program is correct"
            ids = [l["id"] for l in d["lines"]]
            for o in d["options"]:
                idx = ids.index(o["line_id"])
                trial = list(items)
                trial[idx] = (items[idx][0], o["text"])
                assert o["text"] != items[idx][1], (r["id"], "no-op edit")
                assert V.diagnose(_join(trial), exp).passed == o["correct"], (r["id"], o["line_id"], o["text"])
                if o["correct"]:
                    assert idx == bug
                else:
                    assert o["group"] == ("wrong_fix" if idx == bug else "wrong_line"), r["id"]
            assert len({(o["line_id"], o["text"]) for o in d["options"]}) == len(d["options"])


def test_find_bug_options_span_two_lines_even_for_beginners(all_rows):
    n = 0
    for r in all_rows:
        if r["type"] != "find_bug":
            continue
        n += 1
        opts = r["data"]["options"]
        assert len(opts) == 4 and len({o["line_id"] for o in opts}) >= 2, r["id"]
        assert len({o["line_id"] for o in opts[:3]}) >= 2, f"{r['id']}: beginner set on one line"
        assert any(o["line_id"] != r["data"]["bug_line"] for o in opts[:3])
        for level in ("beginner", "intermediate", "advanced"):
            pub = bank.public_puzzle(r, level)
            assert all(set(o) == {"id", "line_id", "text"} for o in pub["options"])
            assert len({o["line_id"] for o in pub["options"]}) >= 2
    assert n >= 280  # 4 native find_bug templates + debug forms of the fill_blank templates


def test_public_views_never_leak(all_rows):
    banned = {"correct", "solution", "solution_code", "is_correct", "answer", "bug_line", "group", "name",
              "note", "distractors", "actual_output", "explanation", "hints"}

    def keys(o):
        if isinstance(o, dict):
            for k, v in o.items():
                yield k
                yield from keys(v)
        elif isinstance(o, list):
            for v in o:
                yield from keys(v)

    for r in all_rows:
        for level in ("beginner", "intermediate", "advanced"):
            pub = bank.public_puzzle(r, level)
            assert not (banned & set(keys(pub))), r["id"]
            assert set(pub) == {"id", "template_id", "topic", "type", "tier", "prompt", "code",
                                "expected_output", "lines", "options"}
            if r["type"] == "predict_output":
                assert pub["expected_output"] is None
            if r["type"] == "parsons":
                assert pub["code"] is None and pub["options"] is None
                assert all(set(l) == {"id", "text"} for l in pub["lines"])
            if pub["options"] is not None:
                assert len(pub["options"]) == min(len(r["data"]["options"]), 3 if level == "beginner" else 4)
            json.dumps(pub, ensure_ascii=False)
