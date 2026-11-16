import json

import httpx
import pytest

from app import bank, tutor
from tests.test_rows import swap


def test_rows_tutor_uses_the_verified_last_attempt(client, monkeypatch):
    def ask(url, payload):
        assert url == "http://n8n.test/webhook/syntax-stack-tutor"
        task = json.loads(payload)
        assert task["task"] == "coach"
        assert task["context"]["error_row"] == 0
        assert task["context"]["error_group"] == "output_mismatch"
        assert task["context"]["actual_output"].split() == ["0", "1"]
        assert "range(2)" in task["context"]["code"]
        return "Vòng lặp dừng trước số nào?"

    monkeypatch.setenv("SYNTAX_STACK_TUTOR_URL", "http://n8n.test/webhook/syntax-stack-tutor")
    monkeypatch.setenv("SYNTAX_STACK_TUTOR_TOKEN", "test")
    monkeypatch.setattr(tutor, "_ask", ask)
    response = client.post("/api/rows/levels/r3/hint?level=1", json={"rows": swap("r3", "t4", "t1")})
    assert response.json() == {"level": 1, "text": "Vòng lặp dừng trước số nào?", "source": "ai"}


def test_rows_tutor_receives_the_selected_verified_step(client, monkeypatch):
    def ask(url, payload):
        step = json.loads(payload)["context"]["current_step"]
        assert step == {"step": 4, "row": 1, "code": "    print(i)", "scope": None,
                        "bindings": {"i": "1"}, "output": "0\n1\n"}
        return "Ở bước này, i bằng 1."

    monkeypatch.setenv("SYNTAX_STACK_TUTOR_URL", "http://n8n.test")
    monkeypatch.setenv("SYNTAX_STACK_TUTOR_TOKEN", "test")
    monkeypatch.setattr(tutor, "_ask", ask)
    attempt = {"rows": swap("r3", "t4", "t1"), "trace_step": 3}
    response = client.post("/api/rows/levels/r3/hint?level=1", json=attempt)
    assert response.json() == {"level": 1, "text": "Ở bước này, i bằng 1.", "source": "ai"}
    attempt["trace_step"] = 48
    assert client.post("/api/rows/levels/r3/hint?level=1", json=attempt).status_code == 422


def test_tutor_falls_back_when_the_webhook_times_out(client, monkeypatch):
    def timeout(url, payload):
        raise httpx.ReadTimeout("test")

    monkeypatch.setenv("SYNTAX_STACK_TUTOR_URL", "http://n8n.test")
    monkeypatch.setenv("SYNTAX_STACK_TUTOR_TOKEN", "test")
    monkeypatch.setattr(tutor, "_ask", timeout)
    attempt = {"rows": swap("r3", "t4", "t1")}
    response = client.post("/api/rows/levels/r3/hint?level=2", json=attempt)
    canned = client.get("/api/rows/levels/r3/hint?level=2&error_group=output_mismatch")
    assert response.status_code == 200
    assert response.json() == canned.json()


@pytest.mark.parametrize("kind", ["fill_blank", "predict_output", "find_bug", "parsons"])
def test_wrong_choice_explanation_and_verified_rematch(client, all_rows, monkeypatch, kind):
    monkeypatch.delenv("SYNTAX_STACK_TUTOR_URL", raising=False)
    original = next(row for row in all_rows if row["type"] == kind and not row["debug_only"])
    if kind == "parsons":
        order = [dict(line, indent=2) for line in original["data"]["solution"]]
        answer = {"order": order}
    else:
        wrong = next(option for option in original["data"]["options"] if not option["correct"])
        answer = {"option_id": wrong["id"]}
    path = f"/api/puzzle/{original['id']}"
    explanation = client.post(path + "/explain", json=answer)
    assert explanation.status_code == 200
    assert explanation.json()["text"]
    assert explanation.json()["source"] == "canned"
    rematch = client.get(path + "/rematch?level=beginner")
    assert rematch.status_code == 200
    puzzle = rematch.json()["puzzle"]
    assert puzzle["id"] != original["id"]
    assert puzzle["template_id"] == original["template_id"]
    assert puzzle["tier"] == original["tier"]
    assert puzzle == bank.public_puzzle(bank.get_puzzle(puzzle["id"]), "beginner")
