import json

import httpx
import pytest

from app import tutor
from tests.test_rows import swap


def _configure(monkeypatch, url="http://n8n.test/hook", limit=None):
    monkeypatch.setenv("SYNTAX_STACK_TUTOR_URL", url)
    monkeypatch.setenv("SYNTAX_STACK_TUTOR_TOKEN", "test")
    if limit is None:
        monkeypatch.delenv("SYNTAX_STACK_TUTOR_DAILY_LIMIT", raising=False)
    else:
        monkeypatch.setenv("SYNTAX_STACK_TUTOR_DAILY_LIMIT", str(limit))


def _fake(monkeypatch, calls):
    def fake(url, payload, *, timeout):
        calls.append(payload)
        return {"text": "Phản hồi " + str(len(calls))}

    monkeypatch.setattr(tutor, "request_tutor", fake)


# ----------------------------------------------------------------------- failure handling


def test_invalid_tutor_url_falls_back_to_canned(monkeypatch):
    _configure(monkeypatch, url="not a url")
    result = tutor.feedback("explain", {"a": 1}, "canned text")
    assert result == {"text": "canned text", "source": "canned"}


@pytest.mark.parametrize("exc", [httpx.InvalidURL("x"), httpx.UnsupportedProtocol("x"),
                                 KeyError("k"), TypeError("t"), ValueError("v")])
def test_other_request_errors_fall_back(monkeypatch, exc):
    _configure(monkeypatch)

    def boom(url, payload, *, timeout):
        raise exc

    monkeypatch.setattr(tutor, "request_tutor", boom)
    assert tutor.feedback("coach", {}, "c")["source"] == "canned"


# ----------------------------------------------------------------------- cost controls


def test_daily_cap_returns_canned_without_calling_out(monkeypatch):
    _configure(monkeypatch, limit=2)
    calls = []
    _fake(monkeypatch, calls)
    sources = [tutor.feedback("coach", {"n": n}, "c")["source"] for n in range(4)]
    assert sources == ["ai", "ai", "canned", "canned"]
    assert len(calls) == 2
    assert tutor.stats() == {"configured": True, "calls_today": 2, "ai_today": 2,
                             "fallback_today": 2, "limit": 2}


def test_limit_zero_disables_the_tutor(monkeypatch):
    _configure(monkeypatch, limit=0)
    calls = []
    _fake(monkeypatch, calls)
    assert tutor.feedback("coach", {}, "c")["source"] == "canned"
    assert calls == []


def test_cache_hits_do_not_count_against_the_cap(monkeypatch):
    _configure(monkeypatch, limit=1)
    calls = []
    _fake(monkeypatch, calls)
    first = tutor.feedback("coach", {"same": True}, "c")
    again = [tutor.feedback("coach", {"same": True}, "c") for _ in range(3)]
    assert first["source"] == "ai" and all(r == first for r in again)
    assert len(calls) == 1
    assert tutor.stats()["calls_today"] == 1
    assert tutor.feedback("coach", {"other": True}, "c")["source"] == "canned"  # cap reached


def test_errors_count_as_calls_and_fallbacks(monkeypatch):
    _configure(monkeypatch)

    def fail(url, payload, *, timeout):
        raise httpx.ReadTimeout("t")

    monkeypatch.setattr(tutor, "request_tutor", fail)
    tutor.feedback("coach", {}, "c")
    s = tutor.stats()
    assert (s["calls_today"], s["ai_today"], s["fallback_today"], s["limit"]) == (1, 0, 1, 500)


def test_not_configured_counts_a_fallback_only(monkeypatch):
    monkeypatch.delenv("SYNTAX_STACK_TUTOR_URL", raising=False)
    tutor.feedback("coach", {}, "c")
    s = tutor.stats()
    assert (s["configured"], s["calls_today"], s["fallback_today"]) == (False, 0, 1)


def test_cache_is_bounded_to_128_entries(monkeypatch):
    _configure(monkeypatch)
    calls = []
    _fake(monkeypatch, calls)
    for n in range(130):
        tutor.feedback("coach", {"n": n}, "c")
    assert len(tutor._cache) == 128
    tutor.feedback("coach", {"n": 0}, "c")  # evicted, so a real call again
    assert len(calls) == 131


def test_log_line_has_task_outcome_latency_and_no_text(monkeypatch, caplog):
    _configure(monkeypatch)
    _fake(monkeypatch, [])
    with caplog.at_level("INFO", logger="app.tutor"):
        tutor.feedback("explain", {"secret": "SECRETCTX"}, "c")
        tutor.feedback("explain", {"secret": "SECRETCTX"}, "c")
    lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("tutor ")]
    assert len(lines) == 2
    assert "task=explain outcome=ai latency_ms=" in lines[0]
    assert "outcome=cached" in lines[1]
    assert all("SECRETCTX" not in m and "Phản hồi" not in m for m in lines)


def test_health_reports_tutor_counters(client, monkeypatch):
    _configure(monkeypatch, limit=7)
    _fake(monkeypatch, [])
    tutor.feedback("coach", {}, "c")
    body = client.get("/api/health").json()
    assert body["ok"] is True and body["puzzles"] > 0
    assert body["tutor"] == {"configured": True, "calls_today": 1, "ai_today": 1,
                             "fallback_today": 0, "limit": 7}


def test_coach_context_has_hint_level_and_deprecated_tier(client, monkeypatch):
    seen = {}

    def ask(url, payload):
        seen.update(json.loads(payload)["context"])
        return "ok"

    _configure(monkeypatch)
    monkeypatch.setattr(tutor, "_ask", ask)
    client.post("/api/rows/levels/r3/hint?level=2", json={"rows": swap("r3", "t4", "t1")})
    assert seen["hint_level"] == 2 and seen["tier"] == 2
