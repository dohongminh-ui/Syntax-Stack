"""Tutor tasks `predict` (Syntax Rows) and `debrief` (Code Rescue run summary)."""
import json

import pytest

from app import tutor
from tests.test_rows import canon, swap

PREDICT = "/api/rows/levels/r3/explain-prediction"
DEBRIEF = "/api/rescue/debrief"


@pytest.fixture
def sent(monkeypatch):
    """Configure the tutor and capture every {task, context} the server sends."""
    monkeypatch.setenv("SYNTAX_STACK_TUTOR_URL", "http://n8n.test/hook")
    monkeypatch.setenv("SYNTAX_STACK_TUTOR_TOKEN", "test")
    monkeypatch.delenv("SYNTAX_STACK_TUTOR_CLIENT_LIMIT", raising=False)
    monkeypatch.delenv("SYNTAX_STACK_TUTOR_DAILY_LIMIT", raising=False)
    calls = []

    def ask(url, payload):
        calls.append(json.loads(payload))
        return "Giải thích của gia sư."

    monkeypatch.setattr(tutor, "_ask", ask)
    return calls


@pytest.fixture
def unconfigured(monkeypatch):
    monkeypatch.delenv("SYNTAX_STACK_TUTOR_URL", raising=False)
    monkeypatch.delenv("SYNTAX_STACK_TUTOR_TOKEN", raising=False)


def wrong_fill(all_rows, topic, n=0):
    """The n-th fill_blank puzzle of a topic, with one of its wrong options."""
    puzzles = [r for r in all_rows if r["type"] == "fill_blank" and r["topic"] == topic and not r["debug_only"]]
    puzzle = puzzles[n]
    option = next(o for o in puzzle["data"]["options"] if not o["correct"])
    return {"puzzle_id": puzzle["id"], "kind": "rescue", "option_id": option["id"]}, puzzle, option


def debrief(client, wrong, **extra):
    body = {"level": "intermediate", "mode": "rescue", "end_reason": "crash", "wrong": wrong, **extra}
    return client.post(DEBRIEF, json=body)


# ------------------------------------------------------------------ predict


def test_predict_fallback_when_tutor_unconfigured(client, unconfigured):
    r = client.post(PREDICT, json={"rows": canon("r3"), "prediction": " 1 2 3 "})
    assert r.status_code == 200
    assert r.json() == {"text": "Bạn đoán:\n1 2 3\nChương trình in:\n0\n1\n2\n"
                        "Mở «Theo dõi từng bước» để xem mỗi dòng print chạy lúc nào.",
                        "source": "canned"}


def test_predict_context_is_built_on_the_server(client, sent):
    r = client.post(PREDICT, json={"rows": canon("r3"), "prediction": "0 1", "trace": False})
    assert r.json() == {"text": "Giải thích của gia sư.", "source": "ai"}
    (call,) = sent
    assert call["task"] == "predict"
    ctx = call["context"]
    assert set(ctx) == {"goal", "code", "prediction", "actual_output", "expected_output", "passed",
                        "trace", "trace_truncated"}
    assert ctx["prediction"] == "0 1"
    assert ctx["actual_output"] == "0\n1\n2" and ctx["expected_output"] == "0\n1\n2"
    assert ctx["passed"] is True
    assert "range(3)" in ctx["code"]
    assert ctx["trace"] and ctx["trace_truncated"] is False
    assert set(ctx["trace"][0]) == {"row", "code", "scope", "bindings", "output"}


def test_predict_trace_is_capped_at_40_steps(client, sent, monkeypatch):
    from app import rows

    real = rows.run_level
    long_trace = [{"row": 0, "code": "x", "scope": None, "bindings": {}, "output": ""}] * 70

    def fake(lv, board, **kw):
        out = real(lv, board, **kw)
        out["trace"] = {"steps": long_trace, "truncated": False}
        return out

    monkeypatch.setattr(rows, "run_level", fake)
    client.post(PREDICT, json={"rows": canon("r3"), "prediction": "9"})
    ctx = sent[0]["context"]
    assert len(ctx["trace"]) == 40 and ctx["trace_truncated"] is True


def test_predict_reports_a_failing_board_too(client, sent):
    r = client.post(PREDICT, json={"rows": swap("r3", "t4", "t1"), "prediction": "0 1 2"})
    assert r.status_code == 200
    ctx = sent[0]["context"]
    assert ctx["passed"] is False and ctx["actual_output"].split() == ["0", "1"]


def test_predict_only_client_data_is_the_prediction(client, sent):
    marker = "ZZ-LEARNER-ZZ"
    client.post(PREDICT, json={"rows": canon("r3"), "prediction": marker})
    payload = json.dumps(sent[0], ensure_ascii=False)
    assert payload.count(marker) == 1 and sent[0]["context"]["prediction"] == marker


@pytest.mark.parametrize("prediction", ["", "   ", None])
def test_predict_requires_a_prediction(client, sent, prediction):
    body = {"rows": canon("r3")}
    if prediction is not None:
        body["prediction"] = prediction
    assert client.post(PREDICT, json=body).status_code == 422
    assert not sent


def test_predict_rejects_an_over_long_prediction(client, sent):
    assert client.post(PREDICT, json={"rows": canon("r3"), "prediction": "x" * 241}).status_code == 422


def test_predict_correct_prediction_is_422(client, sent):
    r = client.post(PREDICT, json={"rows": canon("r3"), "prediction": "0\n1\n2\n"})
    assert r.status_code == 422 and r.json()["detail"] == "Dự đoán này đã đúng."
    assert not sent


@pytest.mark.parametrize("board", [[], "unfinished"])
def test_predict_unfinished_program_is_422(client, sent, board):
    if board == "unfinished":  # only the first row of the loop: `for ...:` with no body
        board = canon("r3")[:1]
    r = client.post(PREDICT, json={"rows": board, "prediction": "0"})
    assert r.status_code == 422
    assert r.json()["detail"] == "Chương trình chưa chạy xong để đối chiếu dự đoán."
    assert not sent


def test_predict_unknown_level_is_404(client, sent):
    r = client.post("/api/rows/levels/nope/explain-prediction", json={"rows": [], "prediction": "1"})
    assert r.status_code == 404


def test_predict_counts_against_the_visitor_quota(client, monkeypatch):
    monkeypatch.setenv("SYNTAX_STACK_TUTOR_URL", "http://n8n.test/hook")
    monkeypatch.setenv("SYNTAX_STACK_TUTOR_TOKEN", "test")
    monkeypatch.setenv("SYNTAX_STACK_TUTOR_CLIENT_LIMIT", "1")
    monkeypatch.setattr(tutor, "request_tutor", lambda url, payload, *, timeout: {"text": "AI"})

    def ask(text, ip):
        r = client.post(PREDICT, json={"rows": canon("r3"), "prediction": text},
                        headers={"CF-Connecting-IP": ip})
        return r.json()["source"]

    assert ask("1", "203.0.113.7") == "ai"
    assert ask("2", "203.0.113.7") == "canned"
    assert ask("3", "198.51.100.2") == "ai"


# ------------------------------------------------------------------ debrief


def test_debrief_fallback_when_tutor_unconfigured(client, all_rows, unconfigured):
    a, _, _ = wrong_fill(all_rows, "loops", 0)
    b, _, _ = wrong_fill(all_rows, "loops", 1)
    r = debrief(client, [a, b])
    assert r.status_code == 200
    assert r.json() == {
        "text": "Ván này bạn sai nhiều nhất ở chủ đề Vòng lặp (2 lần). "
                "Hãy chơi Luyện tập chủ đề này để quen lại quy tắc trước ván sau. "
                "Nhớ rằng hai câu trả lời sai sẽ kết thúc một ván Code Rescue.",
        "source": "canned", "focus_topic": "loops"}
    r = debrief(client, [a, b], end_reason="nofit")
    assert "kết thúc một ván" not in r.json()["text"]


def test_debrief_context_comes_from_the_bank(client, all_rows, sent):
    a, puzzle, option = wrong_fill(all_rows, "conditions")
    r = debrief(client, [a], mode="practice", level="beginner")
    assert r.json() == {"text": "Giải thích của gia sư.", "source": "ai", "focus_topic": "conditions"}
    (call,) = sent
    assert call["task"] == "debrief"
    assert call["context"] == {
        "level": "beginner", "mode": "practice", "end_reason": "crash",
        "topic_counts": {"conditions": 1}, "focus_topic": "conditions",
        "mistakes": [{"topic": "conditions", "type": "fill_blank", "template_id": puzzle["template_id"],
                      "prompt": puzzle["prompt"], "diagnosis": option["message"]}]}


def test_debrief_diagnosis_for_parsons_and_invalid_attempts(client, all_rows, sent):
    parsons = next(r for r in all_rows if r["type"] == "parsons" and not r["debug_only"])
    pid = parsons["id"]
    wrong_order = [dict(line, indent=2) for line in parsons["data"]["solution"]]
    attempts = [
        {"puzzle_id": pid, "kind": "rescue", "order": wrong_order},                        # diagnosed
        {"puzzle_id": pid, "kind": "rescue", "option_id": "nope"},                         # invalid
        {"puzzle_id": pid, "kind": "rescue"},                                              # no attempt
        {"puzzle_id": pid, "kind": "rescue", "order": parsons["data"]["solution"]},        # actually correct
    ]
    assert debrief(client, attempts).status_code == 200
    diagnoses = [m["diagnosis"] for m in sent[0]["context"]["mistakes"]]
    assert diagnoses[0] and diagnoses[1:] == [None, None, None]


def test_debrief_skips_unknown_ids_and_rejects_when_none_remain(client, all_rows, sent):
    a, _, _ = wrong_fill(all_rows, "variables")
    ghost = {"puzzle_id": "no_such_puzzle__999", "kind": "rescue"}
    assert debrief(client, [ghost, a]).status_code == 200
    assert len(sent[0]["context"]["mistakes"]) == 1
    r = debrief(client, [ghost])
    assert r.status_code == 422 and r.json()["detail"] == "Không có lỗi nào để tổng kết."
    assert len(sent) == 1


def test_debrief_limits_and_enums(client, all_rows, sent):
    a, _, _ = wrong_fill(all_rows, "loops")
    assert debrief(client, []).status_code == 422
    assert debrief(client, [a] * 13).status_code == 422
    assert debrief(client, [a] * 12).status_code == 200
    assert debrief(client, [a], end_reason="quit").status_code == 422
    assert debrief(client, [a], mode="x").status_code == 422
    assert debrief(client, [{**a, "puzzle_id": "x" * 81}]).status_code == 422
    assert debrief(client, [{**a, "kind": "other"}]).status_code == 422


def test_debrief_focus_topic_is_the_most_missed_with_first_seen_tie_break(client, all_rows, sent):
    v, _, _ = wrong_fill(all_rows, "variables")
    c, _, _ = wrong_fill(all_rows, "conditions")
    f, _, _ = wrong_fill(all_rows, "functions")
    assert debrief(client, [c, v]).json()["focus_topic"] == "conditions"      # tie: first seen
    assert debrief(client, [v, c, c]).json()["focus_topic"] == "conditions"   # clear majority
    assert debrief(client, [f, v, c, v, f, v]).json()["focus_topic"] == "variables"
    assert sent[-1]["context"]["topic_counts"] == {"functions": 2, "variables": 3, "conditions": 1}
    assert debrief(client, [f, v, v, f]).json()["focus_topic"] == "functions"  # 2-2 tie: first seen


def test_debrief_sends_no_client_text_only_ids(client, all_rows, sent):
    a, _, _ = wrong_fill(all_rows, "loops")
    r = client.post(DEBRIEF, json={"level": "advanced", "mode": "rescue", "end_reason": "nofit",
                                   "wrong": [{**a, "line_id": "SECRET", "extra": "SECRET"}],
                                   "note": "SECRET"})
    assert r.status_code == 200
    assert "SECRET" not in json.dumps(sent[0], ensure_ascii=False)


def test_debrief_counts_against_the_visitor_quota(client, all_rows, monkeypatch):
    a, _, _ = wrong_fill(all_rows, "loops")
    monkeypatch.setenv("SYNTAX_STACK_TUTOR_URL", "http://n8n.test/hook")
    monkeypatch.setenv("SYNTAX_STACK_TUTOR_TOKEN", "test")
    monkeypatch.setenv("SYNTAX_STACK_TUTOR_CLIENT_LIMIT", "1")
    monkeypatch.setattr(tutor, "request_tutor", lambda url, payload, *, timeout: {"text": "AI"})

    def post(mode, ip):
        body = {"level": "beginner", "mode": mode, "end_reason": "nofit", "wrong": [a]}
        return client.post(DEBRIEF, json=body, headers={"CF-Connecting-IP": ip}).json()["source"]

    assert post("rescue", "203.0.113.7") == "ai"
    assert post("practice", "203.0.113.7") == "canned"
    assert post("practice", "198.51.100.2") == "ai"
