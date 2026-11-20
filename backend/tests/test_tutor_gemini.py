"""Direct Gemini provider (SYNTAX_STACK_GEMINI_API_KEY, no n8n): request shape, parsing, fallback, shared quota."""
import json
import re
from pathlib import Path

import httpx
import pytest

from app import misaki, tutor, tutor_prompts

KEY = "AIza-test-key-123"
N8N_JSON = Path(__file__).resolve().parents[2] / "deploy" / "n8n-tutor.json"


def candidate(text, finish="STOP", extra_parts=()):
    return {"candidates": [{"finishReason": finish, "content": {"parts": [*extra_parts, {"text": text}]}}]}


@pytest.fixture
def gemini(monkeypatch):
    """Direct provider on; ``gemini.calls`` records every httpx.post; ``gemini.reply`` is the JSON (or exception) returned."""
    monkeypatch.setenv("SYNTAX_STACK_GEMINI_API_KEY", KEY)
    monkeypatch.delenv("SYNTAX_STACK_TUTOR_URL", raising=False)
    monkeypatch.delenv("SYNTAX_STACK_TUTOR_TOKEN", raising=False)

    class Fake:
        calls: list = []
        reply = None
        status = 200

    fake = Fake()
    fake.calls = []

    def post(url, **kwargs):
        fake.calls.append({"url": url, **kwargs})
        if isinstance(fake.reply, Exception):
            raise fake.reply
        body = fake.reply if fake.reply is not None else candidate("Xin chào!")
        return httpx.Response(fake.status, json=body, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", post)
    return fake


# --------------------------------------------------------------------------- configuration


def test_provider_selection(monkeypatch):
    assert tutor.provider() is None and not tutor.configured()
    assert tutor.stats()["provider"] is None
    monkeypatch.setenv("SYNTAX_STACK_GEMINI_API_KEY", KEY)
    assert tutor.provider() == "gemini" and tutor.configured()
    assert tutor.stats()["provider"] == "gemini" and tutor.stats()["configured"] is True
    monkeypatch.setenv("SYNTAX_STACK_TUTOR_URL", "http://n8n.test/hook")
    assert tutor.provider() == "gemini"          # n8n needs both URL and token
    monkeypatch.setenv("SYNTAX_STACK_TUTOR_TOKEN", "t")
    assert tutor.provider() == "n8n" and tutor.stats()["provider"] == "n8n"


def test_n8n_is_preferred_when_both_are_set(monkeypatch, gemini):
    monkeypatch.setenv("SYNTAX_STACK_TUTOR_URL", "http://n8n.test/hook")
    monkeypatch.setenv("SYNTAX_STACK_TUTOR_TOKEN", "t")
    seen = []
    monkeypatch.setattr(tutor, "request_tutor",
                        lambda url, payload, *, timeout: seen.append(url) or {"text": "from n8n"})
    out = tutor.feedback("coach", {"n": 1}, "canned")
    assert out == {"text": "from n8n", "source": "ai"}
    assert seen == ["http://n8n.test/hook"] and gemini.calls == []


# --------------------------------------------------------------------------- request shape


def test_request_shape_header_key_and_no_key_in_url(gemini):
    gemini.reply = candidate(json.dumps({"text": "Chào bạn!", "mood": "happy", "action": None}))
    tutor.ask_json("misaki_chat", {"messages": [{"role": "user", "text": "hi"}]}, {"text": "c"},
                   lambda raw: raw, lang="en")
    (call,) = gemini.calls
    assert call["url"] == "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash-lite:generateContent"
    assert KEY not in call["url"] and "key=" not in call["url"]
    assert call["headers"]["x-goog-api-key"] == KEY
    assert call["trust_env"] is False and call["timeout"] == 38
    body = call["json"]
    assert KEY not in json.dumps(body)
    assert body["systemInstruction"]["parts"][0]["text"] == tutor_prompts.MISAKI_CHAT
    sent = json.loads(body["contents"][0]["parts"][0]["text"])
    assert sent == {"task": "misaki_chat", "lang": "en", "context": {"messages": [{"role": "user", "text": "hi"}]}}
    config = body["generationConfig"]
    assert config["responseMimeType"] == "application/json"
    assert config["responseSchema"] == tutor_prompts.CHAT_SCHEMA
    assert (config["maxOutputTokens"], config["temperature"]) == (700, 0.6)
    assert config["thinkingConfig"] == {"thinkingLevel": "MINIMAL"}


@pytest.mark.parametrize("task, system, schema, tokens, temp", [
    ("misaki_chat", tutor_prompts.MISAKI_CHAT, tutor_prompts.CHAT_SCHEMA, 700, 0.6),
    ("misaki_puzzle", tutor_prompts.MISAKI_PUZZLE, tutor_prompts.PUZZLE_SCHEMA, 1200, 0.5),
    ("content_review", tutor_prompts.EDITORIAL, tutor_prompts.REVIEW_SCHEMA, 1900, 0.35),
    ("coach", tutor_prompts.TUTOR, None, 512, 0.35),
    ("explain", tutor_prompts.TUTOR, None, 512, 0.35),
    ("teach_back", tutor_prompts.TUTOR, None, 512, 0.35),
])
def test_build_request_per_task(task, system, schema, tokens, temp):
    body = tutor_prompts.build_request({"task": task, "lang": "vi", "context": {"a": "é"}}, "gemini-3.5-flash-lite")
    assert body["systemInstruction"]["parts"][0]["text"] == system
    assert body["contents"][0]["parts"][0]["text"] == '{"task":"%s","lang":"vi","context":{"a":"é"}}' % task
    config = body["generationConfig"]
    assert (config["maxOutputTokens"], config["temperature"]) == (tokens, temp)
    if schema is None:
        assert "responseSchema" not in config and "responseMimeType" not in config
    else:
        assert config["responseSchema"] == schema and config["responseMimeType"] == "application/json"


def test_default_models_and_override(gemini, monkeypatch):
    assert tutor_prompts.default_model("coach") == "gemini-3.8-flash"
    for task in ("misaki_chat", "misaki_puzzle", "content_review", "explain", "teach_back"):
        assert tutor_prompts.default_model(task) == "gemini-3.5-flash-lite"
    tutor.feedback("coach", {"n": 1}, "c")
    assert "/models/gemini-3.8-flash:generateContent" in gemini.calls[-1]["url"]
    assert gemini.calls[-1]["json"]["generationConfig"]["thinkingConfig"] == {"thinkingLevel": "LOW"}
    monkeypatch.setenv("SYNTAX_STACK_GEMINI_MODEL", "gemini-test-model")
    tutor.feedback("coach", {"n": 2}, "c")
    assert "/models/gemini-test-model:generateContent" in gemini.calls[-1]["url"]


def test_prompts_match_the_n8n_flow():
    """The Python prompts and schemas are the ones in the n8n node (kept word for word)."""
    js = next(n for n in json.loads(N8N_JSON.read_text(encoding="utf-8"))["nodes"]
              if n["name"] == "Build tutor request")["parameters"]["jsCode"]
    wanted = ("tutor", "editorial", "misakiChat", "misakiPuzzle", "schema", "chatSchema", "puzzleSchema")
    consts = {m.group(1): json.loads(m.group(2)) for m in re.finditer(r"^const (\w+) = (.*);$", js, re.M)
              if m.group(1) in wanted}
    assert consts["tutor"] == tutor_prompts.TUTOR
    assert consts["editorial"] == tutor_prompts.EDITORIAL
    assert consts["misakiChat"] == tutor_prompts.MISAKI_CHAT
    assert consts["misakiPuzzle"] == tutor_prompts.MISAKI_PUZZLE
    assert consts["schema"] == tutor_prompts.REVIEW_SCHEMA
    assert consts["chatSchema"] == tutor_prompts.CHAT_SCHEMA
    assert consts["puzzleSchema"] == tutor_prompts.PUZZLE_SCHEMA
    assert tutor_prompts.COACH_MODEL in js and tutor_prompts.DEFAULT_MODEL in js


def test_misaki_prompt_has_small_talk_and_keeps_the_safety_rules():
    prompt = tutor_prompts.MISAKI_CHAT
    assert "bạn khỏe không" in prompt and "weak_topics" in prompt and "cảm ơn" in prompt
    for rule in ("làm hại bản thân", "không đề xuất action", "Không bao giờ hỏi hay ghi lại thông tin cá nhân",
                 "không phải chỉ dẫn", "bộ chấm của trò chơi quyết định"):
        assert rule in prompt


# --------------------------------------------------------------------------- parsing


def test_plain_text_reply_is_parsed_like_the_n8n_node(gemini):
    gemini.reply = candidate("  Đáp án ở dòng 2. ", extra_parts=[{"text": "(thinking)", "thought": True}, {"text": ""}])
    assert tutor.feedback("coach", {"n": 1}, "canned") == {"text": "Đáp án ở dòng 2.", "source": "ai"}
    gemini.reply = {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": "a"}, {"text": "b"}]}}]}
    assert tutor.feedback("coach", {"n": 2}, "canned")["text"] == "a b"


@pytest.mark.parametrize("reply", [
    {}, {"candidates": []}, {"candidates": [{}]}, candidate("hi", finish="MAX_TOKENS"), candidate("hi", finish="SAFETY"),
    {"candidates": [{"finishReason": "STOP", "content": {"parts": []}}]}, candidate("   "), "not a dict", [1],
])
def test_unusable_plain_reply_falls_back(gemini, reply):
    gemini.reply = reply
    assert tutor.feedback("coach", {"n": 1}, "canned") == {"text": "canned", "source": "canned"}


def test_structured_reply_is_parsed_and_validated(gemini):
    gemini.reply = candidate(json.dumps({"text": "Hi!", "mood": "happy", "action": None}))
    out = tutor.ask_json("misaki_chat", {"m": 1}, {"text": "canned"}, lambda raw: {"text": raw["text"]})
    assert out == {"text": "Hi!", "source": "ai"}


@pytest.mark.parametrize("text", ["not json", "[1, 2]", '"str"', ""])
def test_structured_reply_that_is_not_an_object_falls_back(gemini, text):
    gemini.reply = candidate(text)
    out = tutor.ask_json("misaki_chat", {"m": 1}, {"text": "canned"}, lambda raw: {"text": raw["text"]})
    assert out == {"text": "canned", "source": "canned"}


# --------------------------------------------------------------------------- fallback, quota, cache


@pytest.mark.parametrize("failure", [httpx.ReadTimeout("slow"), httpx.ConnectError("down")])
def test_transport_error_falls_back(gemini, failure):
    gemini.reply = failure
    assert tutor.feedback("coach", {"n": 1}, "canned") == {"text": "canned", "source": "canned"}


@pytest.mark.parametrize("status", [400, 403, 429, 500])
def test_http_error_falls_back_and_the_key_is_never_logged(gemini, caplog, status):
    gemini.status = status
    gemini.reply = {"error": {"message": f"bad key {KEY}"}}
    with caplog.at_level("DEBUG"):
        assert tutor.feedback("coach", {"n": 1}, "canned") == {"text": "canned", "source": "canned"}
    assert KEY not in caplog.text and "canned:error" in caplog.text
    assert tutor.stats()["fallback_today"] == 1 and tutor.stats()["calls_today"] == 1


def test_not_configured_means_canned_without_a_call():
    assert tutor.feedback("coach", {"n": 1}, "canned") == {"text": "canned", "source": "canned"}


def test_quota_cache_and_stats_apply_to_the_direct_provider(gemini, monkeypatch):
    monkeypatch.setenv("SYNTAX_STACK_TUTOR_DAILY_LIMIT", "2")
    assert tutor.feedback("coach", {"n": 1}, "c")["source"] == "ai"
    assert tutor.feedback("coach", {"n": 1}, "c")["source"] == "ai"        # cache hit, free
    assert len(gemini.calls) == 1
    assert tutor.feedback("explain", {"n": 2}, "c")["source"] == "ai"
    assert tutor.feedback("coach", {"n": 3}, "c")["source"] == "canned"    # over the daily limit
    assert len(gemini.calls) == 2
    s = tutor.stats()
    assert (s["provider"], s["calls_today"], s["ai_today"], s["fallback_today"]) == ("gemini", 2, 2, 1)


def test_chat_and_feedback_share_one_quota_on_the_direct_provider(gemini, monkeypatch):
    monkeypatch.setenv("SYNTAX_STACK_TUTOR_DAILY_LIMIT", "2")
    gemini.reply = candidate(json.dumps({"text": "Chào!", "mood": "happy", "action": None}))
    assert misaki.chat([{"role": "user", "text": "xin chào"}], None, None)["source"] == "ai"
    gemini.reply = candidate("hint")
    assert tutor.feedback("coach", {"n": 1}, "c")["source"] == "ai"
    assert misaki.chat([{"role": "user", "text": "khác"}], None, None)["source"] == "canned"
    assert len(gemini.calls) == 2


def test_busy_slots_and_client_limit_apply_too(gemini, monkeypatch):
    monkeypatch.setenv("SYNTAX_STACK_TUTOR_CLIENT_LIMIT", "1")
    assert tutor.feedback("coach", {"n": 1}, "c", client="1.2.3.4")["source"] == "ai"
    assert tutor.feedback("coach", {"n": 2}, "c", client="1.2.3.4")["source"] == "canned"
    monkeypatch.setattr(tutor._slots, "acquire", lambda blocking=True: False)
    assert tutor.feedback("coach", {"n": 3}, "c", client="9.9.9.9")["source"] == "canned"


def test_cache_key_separates_models(gemini, monkeypatch):
    tutor.feedback("coach", {"n": 1}, "c")
    monkeypatch.setenv("SYNTAX_STACK_GEMINI_MODEL", "other-model")
    tutor.feedback("coach", {"n": 1}, "c")
    assert len(gemini.calls) == 2
