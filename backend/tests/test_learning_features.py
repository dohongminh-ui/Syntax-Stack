import json
from pathlib import Path

import pytest

from app import tutor
from tests.test_rows import canon, swap


@pytest.mark.parametrize("level", ["r1", "r2", "r3", "r4", "r5"])
def test_practice_board_runs_and_exposes_the_authored_mistake(client, level):
    base = f"/api/rows/levels/{level}"
    attempt = client.get(base + "/practice").json()
    response = client.post(base + "/run", json={**attempt, "trace": True}).json()
    assert response["passed"] is False
    assert response["error_group"] == "output_mismatch"
    assert response["trace"]["steps"]


def test_prediction_is_compared_with_actual_output_separately_from_grade(client):
    base = "/api/rows/levels/r4"
    attempt = client.get(base + "/practice").json()
    result = client.post(base + "/run", json={**attempt, "prediction": "1\n3\n6"}).json()
    assert result["passed"] is False and result["prediction"] == {"correct": True}
    result = client.post(base + "/run", json={**attempt, "prediction": "6"}).json()
    assert result["actual_output"] == "1\n3\n6" and result["prediction"] == {"correct": False}
    result = client.post(base + "/run", json={"rows": [], "prediction": "6"}).json()
    assert result["prediction"] == {"correct": None}


@pytest.mark.parametrize("level,old,new,expected", [
    ("r1", "t5", "t3", "8"), ("r2", "t2", "t8", "Trượt"), ("r3", "t4", "t1", "0\n1"),
    ("r4", "t10", "t2", "3"), ("r5", "t5", "t7", "6"),
])
def test_twist_requires_one_replacement_in_a_passing_board(client, level, old, new, expected):
    base = f"/api/rows/levels/{level}/twist"
    baseline = canon(level)
    changed = swap(level, old, new)
    result = client.post(base, json={"baseline": baseline, "rows": changed, "trace": True})
    assert result.status_code == 200
    assert result.json()["passed"] and result.json()["actual_output"] == expected
    assert result.json()["trace"]["steps"]
    assert client.post(base, json={"baseline": baseline, "rows": baseline}).status_code == 422
    assert client.post(base, json={"baseline": changed, "rows": changed}).status_code == 422


def test_teach_back_receives_verified_output_and_player_words(client, monkeypatch):
    def ask(url, payload):
        event = json.loads(payload)
        assert event["task"] == "teach_back"
        assert event["context"]["output"] == "6"
        assert event["context"]["learner_explanation"] == "The loop adds each number."
        return "Which values does it add?"

    monkeypatch.setenv("SYNTAX_STACK_TUTOR_URL", "http://n8n.test")
    monkeypatch.setenv("SYNTAX_STACK_TUTOR_TOKEN", "test")
    monkeypatch.setattr(tutor, "_ask", ask)
    base = "/api/rows/levels/r4/teach-back"
    result = client.post(base, json={"rows": canon("r4"), "reflection": "The loop adds each number."})
    assert result.json() == {"text": "Which values does it add?", "source": "ai"}
    assert client.post(base, json={"rows": canon("r4"), "reflection": " "}).status_code == 422
    assert client.post(base, json={"rows": [], "reflection": "A reflection."}).status_code == 422


def test_editorial_review_rejects_incorrect_output_or_a_correct_distractor(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    from review_content import review_packet

    template = {"id": "loops_range_fill", "topic": "loops", "type": "fill_blank"}
    sample = {"id": "reference", "tier": 1, "solution_code": "for i in range(3):\n    print(i)"}
    draft = {
        "hints": ["Chọn điểm bắt đầu.", "Xem điểm dừng.", "Kiểm tra đối số thứ hai."],
        "followup": {"prompt": "In số từ 1 đến 3.", "code": "for i in range(1, 4):\n    print(i)",
                     "expected_output": "1\n2\n3"},
        "mistakes": [
            {"code": "for i in range(1, 3):\n    print(i)", "why": "Thiếu số 3."},
            {"code": "for i in range(2, 4):\n    print(i)", "why": "Bắt đầu từ số 2."},
            {"code": "for i in range(1, 4):\nprint(i)", "why": "Thiếu thụt lề."},
        ],
    }
    packet = review_packet(draft, template, sample)
    assert packet["status"] == "needs_editor_review"
    assert packet["mistakes"][0]["actual_output"] == "1\n2"
    draft["followup"]["expected_output"] = "1\n2"
    with pytest.raises(ValueError, match="disagrees"):
        review_packet(draft, template, sample)
    draft["followup"]["expected_output"] = "1\n2\n3"
    draft["mistakes"][0]["code"] += "\nprint(3)"
    with pytest.raises(ValueError, match="passes"):
        review_packet(draft, template, sample)
