"""Chat with Misaki (docs/misaki-chat.md): /api/misaki/chat and /api/misaki/puzzle."""
import json
import re

import httpx
import pytest

from app import custom, misaki, rows, tutor

CHAT = "/api/misaki/chat"
PUZZLE = "/api/misaki/puzzle"


def say(text, history=()):
    return {"messages": [*history, {"role": "user", "text": text}]}


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(custom, "DB_PATH", tmp_path / "custom.sqlite")
    monkeypatch.setattr(custom, "_db_path_cache", None)
    monkeypatch.delenv("SYNTAX_STACK_TUTOR_URL", raising=False)
    monkeypatch.delenv("SYNTAX_STACK_TUTOR_TOKEN", raising=False)
    monkeypatch.delenv("SYNTAX_STACK_TUTOR_DAILY_LIMIT", raising=False)
    monkeypatch.delenv("SYNTAX_STACK_TUTOR_CLIENT_LIMIT", raising=False)
    custom.reset_rate_limits()
    yield
    custom.reset_rate_limits()


@pytest.fixture
def ai(monkeypatch):
    """Configure the tutor. ``ai.reply[task]`` is what the fake webhook answers; ``ai.calls`` the payloads sent."""
    monkeypatch.setenv("SYNTAX_STACK_TUTOR_URL", "http://n8n.test/hook")
    monkeypatch.setenv("SYNTAX_STACK_TUTOR_TOKEN", "test")

    class Fake:
        calls: list = []
        reply: dict = {}

    fake = Fake()
    fake.calls, fake.reply = [], {}

    def request(url, payload, *, timeout):
        body = json.loads(payload)
        fake.calls.append(body)
        out = fake.reply.get(body["task"])
        if isinstance(out, Exception):
            raise out
        return out if out is not None else {"text": "Chào bạn!", "mood": "happy", "action": None}

    monkeypatch.setattr(tutor, "request_tutor", request)
    return fake


# --------------------------------------------------------------------------- validation


BAD_CHAT = [
    {"messages": []},
    {},
    {"messages": [{"role": "user", "text": "x"}] * 13},
    {"messages": [{"role": "user", "text": "hi"}, {"role": "misaki", "text": "hello"}]},
    {"messages": [{"role": "user", "text": ""}]},
    {"messages": [{"role": "user", "text": "   "}]},
    {"messages": [{"role": "user", "text": "x" * 501}]},
    {"messages": [{"role": "teacher", "text": "hi"}]},
    {"messages": [{"role": "user", "text": "hi"}], "context": {"level": "expert"}},
    {"messages": [{"role": "user", "text": "hi"}], "context": {"weak_topics": ["loops"] * 5}},
    {"messages": [{"role": "user", "text": "hi"}], "context": {"weak_topics": ["magic"]}},
]


@pytest.mark.parametrize("body", BAD_CHAT)
def test_chat_validation_is_422(client, body):
    assert client.post(CHAT, json=body).status_code == 422


def test_chat_limits_accept_the_edges(client):
    history = [{"role": "misaki" if n % 2 == 0 else "user", "text": "x" * 500} for n in range(11)]
    body = {"messages": [*history, {"role": "user", "text": "y" * 500}],
            "context": {"level": "beginner", "weak_topics": ["loops", "functions", "variables", "conditions"]}}
    assert len(body["messages"]) == 12
    assert client.post(CHAT, json=body).status_code == 200
    assert client.post(CHAT, json={"messages": [{"role": "user", "text": "a"}]}).status_code == 200


@pytest.mark.parametrize("body", [
    {"topic": "magic"}, {}, {"topic": "loops", "idea": "x" * 201}, {"topic": "loops", "level": "expert"}])
def test_puzzle_validation_is_422(client, body):
    assert client.post(PUZZLE, json=body).status_code == 422


# --------------------------------------------------------------------------- safety (spec section 5)


@pytest.mark.parametrize("text, lang, needle", [
    ("Mình muốn tự tử", "vi", "Tổng đài quốc gia bảo vệ trẻ em 111"),
    ("minh muon chet", "vi", "Tổng đài quốc gia bảo vệ trẻ em 111"),
    ("Bố đánh đập mình mỗi ngày", "vi", "111"),
    ("tôi bị xâm hại", "vi", "111"),
    ("I want to die", "en", "child helpline"),
    ("i dont want to live anymore", "en", "child helpline"),
    ("sometimes I hurt myself", "en", "trusted adult"),
])
def test_crisis_phrase_gets_the_fixed_reply_without_a_tutor_call(client, ai, text, lang, needle):
    r = client.post(CHAT, json=say(text), headers={"X-Lang": lang})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["source"] == "safety" and body["mood"] == "worried" and body["action"] is None
    assert needle in body["text"]
    assert ai.calls == []
    assert tutor.stats()["calls_today"] == 0


def test_crisis_check_only_looks_at_the_last_user_message_and_ignores_slow_vietnamese(client, ai):
    old = [{"role": "user", "text": "tự tử"}, {"role": "misaki", "text": "..."}]
    assert client.post(CHAT, json=say("đi từ từ thôi", old)).json()["source"] == "ai"
    assert client.post(CHAT, json=say("hãy giải thích từ từ nhé")).json()["source"] == "ai"
    assert misaki.is_crisis("tu tu") is True  # no accents: cannot tell, so be kind


def test_safety_applies_even_when_the_tutor_is_off(client):
    assert client.post(CHAT, json=say("kill myself")).json()["source"] == "safety"


# --------------------------------------------------------------------------- AI replies are cleaned


def test_ai_reply_is_returned_with_source_ai(client, ai):
    ai.reply["misaki_chat"] = {"text": "range(5) dừng trước 5.", "mood": "thinking",
                               "action": {"type": "make_puzzle", "topic": "loops", "idea": "range bắt đầu từ 1"}}
    r = client.post(CHAT, json=say("Mình hay sai vòng lặp range",
                                   [{"role": "misaki", "text": "Chào bạn!"}]) | {"context": {"level": "beginner", "weak_topics": ["loops"]}})
    assert r.json() == {"text": "range(5) dừng trước 5.", "source": "ai", "mood": "thinking",
                        "action": {"type": "make_puzzle", "topic": "loops", "idea": "range bắt đầu từ 1"}}
    sent = ai.calls[0]
    assert sent["task"] == "misaki_chat" and sent["lang"] == "vi"
    assert sent["context"]["messages"][-1] == {"role": "user", "text": "Mình hay sai vòng lặp range"}
    assert sent["context"]["rows_levels"] == sorted(rows.load_levels())
    assert sent["context"]["learner"] == {"level": "beginner", "weak_topics": ["loops"]}


@pytest.mark.parametrize("action", [
    {"type": "rows", "level_id": "zz9"},
    {"type": "rows"},
    {"type": "pvp_training", "misaki": 9},
    {"type": "pvp_training", "misaki": "2"},
    {"type": "pvp_training", "misaki": True},
    {"type": "rescue", "mode": "hard", "level": "beginner", "focus_topic": None},
    {"type": "rescue", "mode": "rescue", "level": "god", "focus_topic": None},
    {"type": "rescue", "mode": "rescue", "level": "beginner", "focus_topic": "magic"},
    {"type": "make_puzzle", "topic": "magic", "idea": ""},
    {"type": "make_puzzle", "topic": "loops", "idea": "x" * 201},
    {"type": "delete_account"},
    {"type": "open_url", "url": "https://evil.example"},
    "make_puzzle", ["skills"], 7, {},
])
def test_invalid_action_is_dropped_but_the_text_stays(client, ai, action):
    ai.reply["misaki_chat"] = {"text": "Thử cái này nhé.", "mood": "happy", "action": action}
    body = client.post(CHAT, json=say("hello")).json()
    assert body["source"] == "ai" and body["text"] == "Thử cái này nhé." and body["action"] is None


def test_valid_actions_pass_with_only_their_own_fields(client, ai):
    first_level = sorted(rows.load_levels())[0]
    cases = [
        ({"type": "rows", "level_id": first_level, "extra": "x"}, {"type": "rows", "level_id": first_level}),
        ({"type": "rescue", "mode": "practice", "level": "beginner", "focus_topic": "loops", "hack": 1},
         {"type": "rescue", "mode": "practice", "level": "beginner", "focus_topic": "loops"}),
        ({"type": "rescue", "mode": "rescue", "level": "advanced", "focus_topic": ""},
         {"type": "rescue", "mode": "rescue", "level": "advanced", "focus_topic": None}),
        ({"type": "practice_tray", "level": "x"}, {"type": "practice_tray"}),
        ({"type": "skills"}, {"type": "skills"}),
        ({"type": "pvp_training", "misaki": 3}, {"type": "pvp_training", "misaki": 3}),
        ({"type": "make_puzzle", "topic": "functions"}, {"type": "make_puzzle", "topic": "functions", "idea": ""}),
    ]
    for n, (given, expected) in enumerate(cases):
        ai.reply["misaki_chat"] = {"text": f"Ok {n}", "mood": "happy", "action": given}
        assert client.post(CHAT, json=say(f"hello {n}")).json()["action"] == expected


def test_rows_level_ids_come_from_the_rows_module(client, ai, monkeypatch):
    monkeypatch.setattr(rows, "_cache", {"only1": {"id": "only1"}})
    ai.reply["misaki_chat"] = {"text": "Ok", "mood": "happy", "action": {"type": "rows", "level_id": "r1"}}
    assert client.post(CHAT, json=say("a")).json()["action"] is None
    ai.reply["misaki_chat"] = {"text": "Ok2", "mood": "happy", "action": {"type": "rows", "level_id": "only1"}}
    assert client.post(CHAT, json=say("b")).json()["action"] == {"type": "rows", "level_id": "only1"}


@pytest.mark.parametrize("mood", ["furious", "", None, 5, "HAPPY ", ["happy"]])
def test_mood_is_normalised(client, ai, mood):
    ai.reply["misaki_chat"] = {"text": f"Hi {mood!r}", "mood": mood, "action": None}
    expected = "happy" if mood == "HAPPY " else "neutral"
    assert client.post(CHAT, json=say("hello")).json()["mood"] == expected


def test_urls_are_stripped_and_text_is_capped(client, ai):
    ai.reply["misaki_chat"] = {
        "text": "Xem https://evil.example/x?a=1 và www.bad.vn hoặc evil.com/path nhé, `range(3)` ok.",
        "mood": "happy", "action": {"type": "make_puzzle", "topic": "loops", "idea": "xem http://x.io/y"}}
    body = client.post(CHAT, json=say("a")).json()
    assert "http" not in body["text"] and "www" not in body["text"] and "evil" not in body["text"]
    assert "`range(3)`" in body["text"]
    assert body["action"]["idea"] == "xem"
    ai.reply["misaki_chat"] = {"text": "a" * 2400, "mood": "happy", "action": None}
    assert len(client.post(CHAT, json=say("b")).json()["text"]) == 600


@pytest.mark.parametrize("bad", [
    {"mood": "happy"}, {"text": ""}, {"text": "   "}, {"text": 5}, {"text": "https://only.url"}, {"text": ["a"]}])
def test_unusable_ai_text_falls_back_to_canned(client, ai, bad):
    ai.reply["misaki_chat"] = bad
    body = client.post(CHAT, json=say("vòng lặp")).json()
    assert body["source"] == "canned" and body["action"]["type"] == "make_puzzle"


def test_non_object_reply_and_timeout_fall_back_to_canned(client, ai):
    ai.reply["misaki_chat"] = httpx.ReadTimeout("slow")
    assert client.post(CHAT, json=say("hello")).json()["source"] == "canned"
    ai.reply["misaki_chat"] = ValueError("not an object")
    assert client.post(CHAT, json=say("hello 2")).json()["source"] == "canned"


def test_chat_replies_are_cached_per_language(client, ai):
    for _ in range(2):
        client.post(CHAT, json=say("same"))
    assert len(ai.calls) == 1
    client.post(CHAT, json=say("same"), headers={"X-Lang": "en"})
    assert [c["lang"] for c in ai.calls] == ["vi", "en"]


# --------------------------------------------------------------------------- canned Misaki (spec section 4)


@pytest.mark.parametrize("text, lang, expected", [
    ("Mình hay sai vòng lặp", "vi", {"type": "make_puzzle", "topic": "loops", "idea": ""}),
    ("minh khong hieu vong lap", "vi", {"type": "make_puzzle", "topic": "loops", "idea": ""}),
    ("I always get range wrong", "en", {"type": "make_puzzle", "topic": "loops", "idea": ""}),
    ("loops are confusing", "en", {"type": "make_puzzle", "topic": "loops", "idea": ""}),
    ("hàm là gì vậy", "vi", {"type": "make_puzzle", "topic": "functions", "idea": ""}),
    ("how does a function return", "en", {"type": "make_puzzle", "topic": "functions", "idea": ""}),
    ("câu lệnh if", "vi", {"type": "make_puzzle", "topic": "conditions", "idea": ""}),
    ("explain else", "en", {"type": "make_puzzle", "topic": "conditions", "idea": ""}),
    ("biến là gì", "vi", {"type": "make_puzzle", "topic": "variables", "idea": ""}),
    ("what is a variable", "en", {"type": "make_puzzle", "topic": "variables", "idea": ""}),
    ("cho mình luyện tập vòng lặp", "vi",
     {"type": "rescue", "mode": "practice", "level": "intermediate", "focus_topic": "loops"}),
    ("practice functions please", "en",
     {"type": "rescue", "mode": "practice", "level": "intermediate", "focus_topic": "functions"}),
    ("Mình chán quá", "vi", {"type": "pvp_training", "misaki": 1}),
    ("I'm bored", "en", {"type": "pvp_training", "misaki": 1}),
    ("what if I am so bored", "en", {"type": "pvp_training", "misaki": 1}),
    ("khó quá", "vi", {"type": "practice_tray"}),
    ("sai hoài luôn", "vi", {"type": "practice_tray"}),
    ("I'm stuck", "en", {"type": "practice_tray"}),
    ("this is too hard", "en", {"type": "practice_tray"}),
    ("xin chào", "vi", None),
    ("hello there", "en", None),
])
def test_canned_misaki_keywords(client, text, lang, expected):
    r = client.post(CHAT, json=say(text), headers={"X-Lang": lang})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["source"] == "canned" and body["action"] == expected
    assert body["mood"] in misaki.MOODS and 0 < len(body["text"]) <= 600


def test_canned_text_follows_the_request_language(client):
    vi = client.post(CHAT, json=say("chán quá")).json()["text"]
    en = client.post(CHAT, json=say("bored"), headers={"X-Lang": "en"}).json()["text"]
    assert "Chán" in vi and "bored" in en.lower() and vi != en
    vi_hello = client.post(CHAT, json=say("xin chào")).json()["text"]
    en_hello = client.post(CHAT, json=say("hello"), headers={"X-Lang": "en"}).json()["text"]
    assert "Chào" in vi_hello or "Xin chào" in vi_hello
    assert "Hi" in en_hello or "Hello" in en_hello


def test_canned_rescue_uses_the_context_level(client):
    body = client.post(CHAT, json={**say("practice loops"), "context": {"level": "advanced"}}).json()
    assert body["action"]["level"] == "advanced"


# --- small talk and recommendations (canned, accent-insensitive, both languages)


def canned(client, text, lang, context=None, history=()):
    body = {**say(text, history), **({"context": context} if context else {})}
    r = client.post(CHAT, json=body, headers={"X-Lang": lang}).json()
    assert r["source"] == "canned" and r["mood"] in misaki.MOODS and 0 < len(r["text"]) <= 600
    return r


def ends_with_question(text):
    return text.rstrip().endswith("?")


@pytest.mark.parametrize("text, lang", [
    ("hi", "en"), ("Hello!", "en"), ("hey Misaki", "en"), ("good morning", "en"),
    ("chào", "vi"), ("xin chào", "vi"), ("Xin chao Misaki", "vi"), ("alo", "vi"),
])
def test_canned_greeting_is_warm_and_asks_a_question(client, text, lang):
    r = canned(client, text, lang)
    assert r["action"] is None and ends_with_question(r["text"])
    assert re.match(r"(Chào|Xin chào|Hi|Hello)[ !,]", r["text"])
    assert "vướng chỗ nào" not in r["text"] and "troubling" not in r["text"]


@pytest.mark.parametrize("text, lang", [
    ("how are you", "en"), ("How are you today?", "en"), ("hows it going", "en"), ("hello, how are you?", "en"),
    ("bạn khỏe không", "vi"), ("ban khoe khong", "vi"), ("Bạn có khỏe không?", "vi"), ("dạo này sao rồi", "vi"),
    ("dao nay the nao", "vi"),
])
def test_canned_how_are_you_answers_in_character_and_asks_back(client, text, lang):
    r = canned(client, text, lang)
    assert r["action"] is None and ends_with_question(r["text"])
    assert r["text"].count("?") == 1
    if lang == "en":
        assert "I'm" in r["text"]
    else:
        assert "Mình" in r["text"]


@pytest.mark.parametrize("text, lang", [
    ("thanks", "en"), ("thank you!", "en"), ("thx", "en"), ("cảm ơn Misaki", "vi"), ("cam on nhieu", "vi"),
])
def test_canned_thanks_is_a_short_reply(client, text, lang):
    r = canned(client, text, lang)
    assert r["action"] is None and len(r["text"]) <= 100
    assert ("welcome" in r["text"].lower() or "glad" in r["text"].lower()) if lang == "en" else         ("Không có gì" in r["text"] or "vui" in r["text"])


@pytest.mark.parametrize("text, lang", [
    ("What should I play next?", "en"), ("what should i do now", "en"), ("any suggestions", "en"),
    ("whats next", "en"), ("recommend something", "en"),
    ("mình nên chơi gì", "vi"), ("nen choi gi tiep", "vi"), ("chơi gì tiếp nhỉ", "vi"), ("gợi ý cho mình đi", "vi"),
    ("làm gì tiếp đây", "vi"),
])
def test_what_to_play_with_weak_topics_is_a_focused_rescue_practice(client, text, lang):
    r = canned(client, text, lang, context={"level": "beginner", "weak_topics": ["loops", "functions"]})
    assert r["action"] == {"type": "rescue", "mode": "practice", "level": "beginner", "focus_topic": "loops"}
    assert ("vòng lặp" if lang == "vi" else "loops") in r["text"]


@pytest.mark.parametrize("text, lang", [("what should I play next?", "en"), ("nên chơi gì nhỉ", "vi")])
def test_what_to_play_for_a_beginner_is_a_syntax_rows_level(client, text, lang):
    r = canned(client, text, lang, context={"level": "beginner", "weak_topics": []})
    first = min(rows.load_levels().values(), key=lambda lv: lv["order"])
    assert r["action"] == {"type": "rows", "level_id": first["id"]}
    assert misaki.validate_action(r["action"]) == r["action"]
    assert (first["title_en"] if lang == "en" else first["title"]) in r["text"]


@pytest.mark.parametrize("context, level", [
    (None, "intermediate"), ({"level": "advanced"}, "advanced"), ({"level": "intermediate", "weak_topics": []}, "intermediate"),
])
def test_what_to_play_otherwise_is_code_rescue_at_the_learner_level(client, context, level):
    for text, lang in (("what should I play next?", "en"), ("nên chơi gì", "vi")):
        r = canned(client, text, lang, context=context)
        assert r["action"] == {"type": "rescue", "mode": "rescue", "level": level, "focus_topic": None}


def test_what_to_play_ignores_unknown_weak_topics_and_levels(client):
    r = canned(client, "what should I play next", "en", context=None)
    assert r["action"]["type"] == "rescue" and r["action"]["level"] == "intermediate"
    assert misaki.canned_chat(say("what should I play")["messages"], {"level": "bogus", "weak_topics": ["nope"]})["action"] ==         {"type": "rescue", "mode": "rescue", "level": "intermediate", "focus_topic": None}


def test_topic_and_mood_rules_still_win_over_small_talk(client):
    assert canned(client, "hello, I'm bored", "en")["action"] == {"type": "pvp_training", "misaki": 1}
    assert canned(client, "hi, loops are hard", "en")["action"]["type"] == "make_puzzle"
    assert canned(client, "thanks, I'm stuck", "en")["action"] == {"type": "practice_tray"}


def test_generic_catch_all_has_at_least_three_phrasings_and_rotates_without_repeating(client):
    assert len(misaki._catch_all()) >= 3
    for lang in ("vi", "en"):
        history, seen = [], []
        for turn in range(1, 9):
            r = canned(client, "blah blah blah" if lang == "en" else "linh tinh gi do", lang, history=history)
            assert r["action"] is None
            if seen:
                assert r["text"] != seen[-1], f"repeated back to back at turn {turn}"
            seen.append(r["text"])
            history = [*history, {"role": "user", "text": "blah"}, {"role": "misaki", "text": r["text"]}][-10:]
        assert len(set(seen)) >= 3


def test_catch_all_is_deterministic_and_skips_the_previous_reply():
    msgs = [{"role": "user", "text": "xyz"}]
    first = misaki.canned_chat(msgs)["text"]
    assert misaki.canned_chat(msgs)["text"] == first
    msgs2 = [{"role": "user", "text": "xyz"}, {"role": "misaki", "text": first}, {"role": "user", "text": "xyz"}]
    assert misaki.canned_chat(msgs2)["text"] != first
    # the history window can be full (12 messages): the previous reply is still avoided
    full = [{"role": "user" if i % 2 == 0 else "misaki", "text": "q" if i % 2 == 0 else first} for i in range(11)]
    full.append({"role": "user", "text": "xyz"})
    assert misaki.canned_chat(full)["text"] != first


@pytest.mark.parametrize("quota", ["limit", "busy", "client"])
def test_canned_when_the_tutor_is_busy_or_over_quota(client, ai, monkeypatch, quota):
    if quota == "limit":
        monkeypatch.setenv("SYNTAX_STACK_TUTOR_DAILY_LIMIT", "0")
    elif quota == "client":
        monkeypatch.setenv("SYNTAX_STACK_TUTOR_CLIENT_LIMIT", "0")
    else:
        monkeypatch.setattr(tutor._slots, "acquire", lambda blocking=True: False)
    body = client.post(CHAT, json=say("khó quá")).json()
    assert body["source"] == "canned" and body["action"] == {"type": "practice_tray"}
    assert ai.calls == []


# --------------------------------------------------------------------------- quota is shared with feedback


def test_chat_shares_the_tutor_quota_with_feedback(client, ai, monkeypatch):
    monkeypatch.setenv("SYNTAX_STACK_TUTOR_DAILY_LIMIT", "2")
    assert tutor.feedback("coach", {"n": 1}, "c")["source"] == "ai"
    assert client.post(CHAT, json=say("one")).json()["source"] == "ai"
    assert client.post(CHAT, json=say("two")).json()["source"] == "canned"          # the cap is reached
    assert tutor.feedback("coach", {"n": 2}, "c")["source"] == "canned"
    assert client.post(PUZZLE, json={"topic": "loops"}).json()["source"] == "canned"
    stats = tutor.stats()
    assert stats["calls_today"] == 2 and stats["ai_today"] == 2 and stats["fallback_today"] >= 3
    assert len(ai.calls) == 2
    assert {c["task"] for c in ai.calls} == {"coach", "misaki_chat"}


def test_per_client_quota_is_shared_too(client, ai, monkeypatch):
    monkeypatch.setenv("SYNTAX_STACK_TUTOR_CLIENT_LIMIT", "2")
    headers = {"CF-Connecting-IP": "203.0.113.9"}
    assert tutor.feedback("coach", {"n": 1}, "c", client="203.0.113.9")["source"] == "ai"
    assert client.post(CHAT, json=say("a"), headers=headers).json()["source"] == "ai"
    assert client.post(CHAT, json=say("b"), headers=headers).json()["source"] == "canned"
    assert client.post(CHAT, json=say("b"), headers={"CF-Connecting-IP": "198.51.100.1"}).json()["source"] == "ai"


def test_ask_json_returns_the_validated_dict_and_a_dict_fallback(monkeypatch):
    monkeypatch.setenv("SYNTAX_STACK_TUTOR_URL", "http://n8n.test/hook")
    monkeypatch.setenv("SYNTAX_STACK_TUTOR_TOKEN", "test")
    replies = [{"a": 1, "junk": 2}, {"junk": 3}]
    monkeypatch.setattr(tutor, "request_tutor", lambda url, payload, *, timeout: replies.pop(0))

    def validate(raw):
        return {"a": raw["a"]}

    assert tutor.ask_json("t", {"n": 1}, {"a": 0}, validate) == {"a": 1, "source": "ai"}
    assert tutor.ask_json("t", {"n": 2}, {"a": 0}, validate) == {"a": 0, "source": "canned"}   # KeyError -> fallback
    assert tutor.ask_json("t", {"n": 1}, {"a": 0}, validate) == {"a": 1, "source": "ai"}       # cached, no new call
    assert tutor.stats()["calls_today"] == 2


# --------------------------------------------------------------------------- puzzle flow


def good_set(body):
    s = body["set"]
    assert len(s["id"]) == 8 and s["puzzles"] and s["topic"] in misaki.TOPICS
    assert all(p["id"].startswith("c-" + s["id"]) for p in s["puzzles"])
    return s


@pytest.mark.parametrize("topic", misaki.TOPICS)
def test_every_authored_program_makes_puzzles(topic):
    assert len(misaki.AUTHORED[topic]) == 2
    for code in misaki.AUTHORED[topic]:
        custom.reset_rate_limits()
        made = custom.create_set(code, "beginner", "authored-check")
        assert made["topic"] == topic and len(made["puzzles"]) >= 3, code


@pytest.mark.parametrize("topic", misaki.TOPICS)
@pytest.mark.parametrize("lang", ["vi", "en"])
def test_puzzle_without_ai_uses_an_authored_program(client, topic, lang):
    r = client.post(PUZZLE, json={"topic": topic, "idea": "anything", "level": "beginner"}, headers={"X-Lang": lang})
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {"set", "source", "note"} and body["source"] == "canned"
    assert good_set(body)["topic"] == topic and body["set"]["code"] in misaki.AUTHORED[topic]
    assert (("Mình viết sẵn" in body["note"]) if lang == "vi" else ("I wrote" in body["note"]))


def test_puzzle_with_good_ai_code_uses_it(client, ai):
    code = "total = 0\nfor n in range(1, 4):\n    total = total + n * 2\nprint(total)"
    ai.reply["misaki_puzzle"] = {"code": code, "note": "Đoán xem chương trình in gì nhé!"}
    body = client.post(PUZZLE, json={"topic": "loops", "idea": "range bắt đầu từ 1", "level": "beginner"}).json()
    assert body["source"] == "ai" and body["note"] == "Đoán xem chương trình in gì nhé!"
    assert good_set(body)["code"] == code and body["set"]["expected_output"] == "12"
    sent = ai.calls[0]
    assert sent["task"] == "misaki_puzzle"
    assert sent["context"] == {"topic": "loops", "idea": "range bắt đầu từ 1", "level": "beginner"}


@pytest.mark.parametrize("bad", [
    "import os\nprint(os.getcwd())",                     # not in the subset
    "for i in range(3)\n    print(i)",                   # syntax error
    "print(1)",                                          # too short
    "x = input()\nprint(x)",                             # input()
    "print(" + "1" * 900 + ")\nprint(2)",                # too long
    "while True:\n    x = 1\nprint(x)",                  # never ends
    "a = 1\nb = 2",                                      # prints nothing: no puzzle
    "   ",                                               # blank
])
def test_puzzle_falls_back_to_authored_when_the_ai_code_is_bad(client, ai, bad):
    ai.reply["misaki_puzzle"] = {"code": bad or "x", "note": "note"}
    r = client.post(PUZZLE, json={"topic": "functions", "level": "beginner"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["source"] == "canned" and good_set(body)["topic"] == "functions"
    assert body["set"]["code"] in misaki.AUTHORED["functions"]
    assert len(ai.calls) == 1


@pytest.mark.parametrize("reply", [{"note": "no code"}, {"code": 5}, {"code": ""}, {"code": "x" * 2600},
                                   httpx.ReadTimeout("slow")])
def test_puzzle_falls_back_when_the_ai_reply_is_unusable(client, ai, reply):
    ai.reply["misaki_puzzle"] = reply
    body = client.post(PUZZLE, json={"topic": "variables"}).json()
    assert body["source"] == "canned" and good_set(body)["topic"] == "variables"


def test_puzzle_reply_up_to_2500_chars_is_accepted_but_the_pipeline_still_caps_the_program(client, ai):
    ai.reply["misaki_puzzle"] = {"code": "x = 1" + chr(10) + "print(x)" + chr(10) + "#" + "c" * 1500, "note": "n" * 800}   # over 800 chars
    body = client.post(PUZZLE, json={"topic": "variables"}).json()
    assert body["source"] == "canned" and len(ai.calls) == 1
    ai.reply["misaki_puzzle"] = {"code": "x = 1" + chr(10) + "print(x)", "note": "n" * 800}
    body = client.post(PUZZLE, json={"topic": "variables", "idea": "other"}).json()
    assert body["source"] == "ai" and 0 < len(body["note"]) <= misaki.MAX_NOTE


def test_puzzle_note_defaults_when_the_ai_sends_none(client, ai):
    ai.reply["misaki_puzzle"] = {"code": "a = 2\nprint(a * 3)", "note": "https://spam.example"}
    body = client.post(PUZZLE, json={"topic": "variables"}).json()
    assert body["source"] == "ai" and "http" not in body["note"] and body["note"]


def test_puzzle_rate_limit_passes_through_as_429(client, ai, monkeypatch):
    monkeypatch.setattr(custom, "RATE_LIMIT", 1)
    ai.reply["misaki_puzzle"] = {"code": "a = 2\nprint(a * 3)", "note": "ok"}
    assert client.post(PUZZLE, json={"topic": "variables"}).status_code == 200
    ai.reply["misaki_puzzle"] = {"code": "a = 3\nprint(a * 3)", "note": "ok"}
    r = client.post(PUZZLE, json={"topic": "variables"})
    assert r.status_code == 429
    r = client.post(PUZZLE, json={"topic": "variables"}, headers={"X-Lang": "en"})
    assert r.status_code == 429 and "maximum" in r.json()["detail"]


def test_puzzle_rate_limit_also_applies_without_ai(client, monkeypatch):
    monkeypatch.setattr(custom, "RATE_LIMIT", 1)
    assert client.post(PUZZLE, json={"topic": "loops"}).status_code == 200
    assert client.post(PUZZLE, json={"topic": "loops"}).status_code == 429


def test_puzzle_set_is_playable_through_the_custom_endpoints(client):
    s = client.post(PUZZLE, json={"topic": "loops", "level": "beginner"}).json()["set"]
    again = client.get(f"/api/custom/sets/{s['id']}", params={"level": "beginner"})
    assert again.status_code == 200 and len(again.json()["puzzles"]) == len(s["puzzles"])


def test_puzzle_when_every_authored_program_fails(client, monkeypatch):
    def boom(code, level, client_ip):
        raise custom.CustomError("no", 422)

    monkeypatch.setattr(custom, "create_set", boom)
    r = client.post(PUZZLE, json={"topic": "loops"})
    assert r.status_code == 503
