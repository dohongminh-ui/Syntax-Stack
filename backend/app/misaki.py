"""Chat with Misaki (docs/misaki-chat.md): safety check, reply validation, canned Misaki, puzzle flow.

The validator decides, the AI explains: nothing Misaki writes is trusted. Her actions go through a fixed whitelist
(``validate_action``) and every program she writes goes through ``custom.create_set`` (AST whitelist, sandbox,
generator) like a pasted one. Chat content is never logged or stored here.
"""
from __future__ import annotations

import logging
import random
import re
import unicodedata
from functools import partial
from typing import Any, Optional

from . import bank, custom, i18n, rows, tutor, tutor_prompts
from .i18n import tr

logger = logging.getLogger(__name__)

TOPICS = ("variables", "conditions", "loops", "functions")
LEVELS = ("beginner", "intermediate", "advanced")
MOODS = ("neutral", "happy", "excited", "thinking", "worried", "sad", "shy", "dizzy")
MAX_TEXT = 600          # reply text sent to the client
MAX_RAW_TEXT = 2500     # what we accept from the tutor before cutting it down
MAX_IDEA = 200
MAX_NOTE = 300
MAX_CODE = 2500         # a puzzle reply is bigger than a chat reply; create_set enforces its own, lower, limit
MAX_REVIEW_ATTEMPTS = 8  # up to two submissions per puzzle in the latest set
MISAKI_LEVELS = (1, 2, 3, 4)
ACTION_TYPES = ("rescue", "rows", "practice_tray", "skills", "pvp_training", "make_puzzle")

TOPIC_NAMES = {
    "variables": ("biến", "variables"), "conditions": ("câu điều kiện", "conditions"),
    "loops": ("vòng lặp", "loops"), "functions": ("hàm", "functions"),
}


def topic_name(topic: str) -> str:
    vi, en = TOPIC_NAMES[topic]
    return tr(vi, en)


# --------------------------------------------------------------------------- text helpers


def fold(text: str) -> str:
    """Lower-case, accent-free (``đ`` -> ``d``), apostrophes dropped, punctuation turned into single spaces."""
    text = text.lower().replace("đ", "d").replace("’", "").replace("'", "")
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


_URL = re.compile(
    r"(?:https?://|ftp://|www\.)\S+"
    r"|\b[\w-]+(?:\.[\w-]+)*\.(?:com|net|org|vn|io|edu|gov|info|xyz|app|dev|ly|me|co|tv|gg)\b(?:/\S*)?",
    re.I)


def strip_urls(text: str) -> str:
    return re.sub(r"[ \t]{2,}", " ", _URL.sub("", text)).strip()


def clean_text(value: Any, limit: int) -> str:
    """Plain text from the tutor: a string, URLs removed, at most ``limit`` characters. ``ValueError`` if nothing is left."""
    if not isinstance(value, str):
        raise ValueError("text is not a string")
    text = strip_urls(value.replace("\r\n", "\n").strip())
    if not text:
        raise ValueError("empty text")
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def normalize_mood(value: Any) -> str:
    if isinstance(value, str) and value.strip().lower() in MOODS:
        return value.strip().lower()
    return "neutral"


# --------------------------------------------------------------------------- safety (spec section 5)

# Folded (accent-free) patterns. Kept narrow on purpose: a false alarm only costs a kind, fixed reply.
_CRISIS = re.compile(r"\b(?:" + "|".join([
    # Vietnamese
    r"tu sat", r"tu tu", r"tu van tu", r"muon chet", r"chet di", r"chet quach", r"chet cho xong",
    r"khong muon song", r"het muon song", r"chan song", r"muon bien mat khoi", r"ket thuc cuoc song",
    r"tu lam (?:dau|dau minh|hai|bi thuong|minh bi thuong|minh dau)", r"tu hai (?:ban than|minh)",
    r"cat tay", r"rach tay", r"uong thuoc ngu de chet", r"nhay (?:lau|cau)",
    r"bi (?:danh dap|bao hanh|bao luc|hiep|cuong buc|xam hai|lam dung|nguoc dai|dam doi)",
    r"(?:bo|me|ba|cha|anh|chi|thay|ong|chu|bac|nguoi lon) (?:toi |minh )?(?:danh dap|danh toi|danh minh|dam toi|bao hanh)",
    r"bi (?:bo|me|ba|cha|anh|chi|thay|ong|chu|bac|nguoi lon) (?:danh|dam|dap)",
    # English
    r"suicid\w*", r"kill (?:myself|my self)", r"killing myself", r"want to die", r"wanna die", r"wish i (?:was|were) dead",
    r"better off dead", r"end (?:my|it all|my own) life", r"ending my life", r"dont want to (?:live|be alive|exist)",
    r"do not want to (?:live|be alive|exist)", r"no reason to live", r"self harm\w*", r"hurt(?:ing)? myself",
    r"harm(?:ing)? myself", r"cut(?:ting)? myself", r"hurts? me on purpose", r"being (?:abused|molested|raped|hit)",
    r"(?:abuses|abused|molests|molested|rapes|raped|touches|touched) me", r"sexually abus\w*",
    r"hits me", r"beats me", r"beating me",
]) + r")\b")


_CRISIS_JA = re.compile(r"死にたい|自殺したい|生きていたくない|自分を傷つけたい|虐待されている")


def is_crisis(text: str) -> bool:
    """True when the message reads as a serious personal or safety issue (self-harm, abuse, wanting to die...)."""
    if not isinstance(text, str) or not text.strip():
        return False
    if _CRISIS_JA.search(text):
        return True
    folded = fold(text)
    if not _CRISIS.search(folded):
        return False
    # "từ từ" (slowly) folds to "tu tu" (suicide, tự tử): the accented slow form alone is not a crisis.
    nfc = unicodedata.normalize("NFC", text.lower())
    if "từ từ" in nfc and "tự tử" not in nfc and not _CRISIS.search(re.sub(r"\btu tu\b", " ", folded)):
        return False
    return True


def safety_reply() -> dict:
    return {
        "text": tr(
            "Mình rất vui vì bạn đã nói với mình. Chuyện này quan trọng lắm, nhưng mình chỉ là một nhân vật trong "
            "trò chơi nên không giúp bạn đủ được. Bạn hãy nói ngay với một người lớn bạn tin tưởng hoặc thầy cô nhé. "
            "Bạn cũng có thể gọi Tổng đài quốc gia bảo vệ trẻ em 111 (miễn phí, 24/7).",
            "I'm really glad you told me. This is important, and I'm only a game character, so I can't help "
            "you enough. Please talk to a trusted adult or a teacher right now. You can also call your local "
            "emergency number or a child helpline."),
        "source": "safety", "mood": "worried", "action": None,
    }


# --------------------------------------------------------------------------- actions (spec section 2)


def rows_level_ids() -> set[str]:
    return set(rows.load_levels())


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def validate_action(raw: Any) -> Optional[dict]:
    """The action as one of the whitelisted shapes (only the known fields), or ``None`` when it is invalid."""
    if not isinstance(raw, dict):
        return None
    kind = raw.get("type")
    if kind == "rescue":
        mode, level, focus = raw.get("mode"), raw.get("level"), raw.get("focus_topic")
        if focus == "":
            focus = None
        if mode not in ("rescue", "practice") or level not in LEVELS or not (focus is None or focus in TOPICS):
            return None
        return {"type": "rescue", "mode": mode, "level": level, "focus_topic": focus}
    if kind == "rows":
        level_id = raw.get("level_id")
        if not isinstance(level_id, str) or level_id not in rows_level_ids():
            return None
        return {"type": "rows", "level_id": level_id}
    if kind in ("practice_tray", "skills"):
        return {"type": kind}
    if kind == "pvp_training":
        level = raw.get("misaki")
        if not _is_int(level) or level not in MISAKI_LEVELS:
            return None
        return {"type": "pvp_training", "misaki": level}
    if kind == "make_puzzle":
        topic, idea = raw.get("topic"), raw.get("idea", "")
        if topic not in TOPICS:
            return None
        if idea is None:
            idea = ""
        if not isinstance(idea, str):
            return None
        idea = strip_urls(idea)
        if len(idea) > MAX_IDEA:
            return None
        return {"type": "make_puzzle", "topic": topic, "idea": idea}
    return None


# Letters only Vietnamese uses (đ, ă, ơ, ư and the vowels with a hook or dot below). Three or more in an English
# reply means the model ignored the language: treat it as unusable so the learner gets the authored line instead.
_VI_LETTERS = set("đăơưạảấầẩẫậắằẳẵặẹẻẽếềểễệỉịọỏốồổỗộớờởỡợụủứừửữựỳỵỷỹ")


def wrong_language(text: str, language: Optional[str] = None) -> bool:
    if language == "ja":
        return re.search(r"[\u3041-\u3096\u30a1-\u30fa]", text) is None
    return i18n.resolve(language) == "en" and sum(ch in _VI_LETTERS for ch in text.lower()) >= 3


def speech_text(value: Any, language: str) -> Optional[str]:
    try:
        text = clean_text(value, MAX_TEXT)
        if not wrong_language(text, language):
            return text
    except ValueError:
        pass
    return None


def translate_speech(text: str, language: str, client: Optional[str]) -> Optional[str]:
    result = tutor.feedback(tutor_prompts.VOICE_TRANSLATION_TASK,
                            {"text": text, "voice_language": language}, "", client=client)
    return speech_text(result["text"], language)


def validate_chat_reply(raw: dict, *, requested_topic: Optional[str] = None, follow_up: bool = False,
                        previous_action: Optional[dict] = None, review_topic: Optional[str] = None,
                        voice_language: Optional[str] = None) -> dict:
    """Only a validated native game tool can supply a button."""
    raw = tutor_prompts.decode_chat_call(raw.get("function_calls"))
    text = raw.get("text")
    if isinstance(text, str):
        text = text[:MAX_RAW_TEXT]
        if wrong_language(text):
            raise ValueError("reply not in the request's language")
    text = clean_text(text, MAX_TEXT)
    proposal = raw["action"]
    kind = proposal["type"] if proposal else None
    if kind == "repeat_offer":
        action = previous_action
    elif kind == "follow_up_puzzle":
        action = validate_action({"type": "make_puzzle", "topic": review_topic, "idea": proposal.get("idea")})
    else:
        action = validate_action(proposal)
    if proposal is not None and action is None:
        raise ValueError("invalid Misaki tool arguments")
    if follow_up and kind not in ("make_puzzle", "follow_up_puzzle"):
        raise ValueError("a requested follow-up needs a playable puzzle")
    action_topic = (action.get("focus_topic") or action.get("topic")) if action else None
    if kind != "repeat_offer" and requested_topic and action_topic and action_topic != requested_topic:
        raise ValueError("action focuses on a different topic from the learner's request")
    reply = {"text": text, "mood": normalize_mood(raw.get("mood")), "action": action}
    if voice_language and (spoken := speech_text(raw.get("speech_text"), voice_language)):
        reply["speech_text"] = spoken
    return reply


def validate_puzzle_reply(raw: dict, *, voice_language: Optional[str] = None) -> dict:
    """Tutor reply -> ``{"code", "note"}``; ``ValueError`` when there is no program."""
    code = raw.get("code")
    if not isinstance(code, str) or not code.strip() or len(code) > MAX_CODE:
        raise ValueError("missing or invalid code")
    note = raw.get("note")
    try:
        note = clean_text(note, MAX_NOTE) if note is not None else ""
        if wrong_language(note):
            note = ""
    except ValueError:
        note = ""
    reply = {"code": code, "note": note}
    if note and voice_language and (spoken := speech_text(raw.get("speech_text"), voice_language)):
        reply["speech_text"] = spoken
    return reply


# --------------------------------------------------------------------------- canned Misaki (spec section 4)

_PRACTICE = re.compile(r"\b(luyen tap|luyen|practice|practise|drill|choi)\b")
_BORED = re.compile(r"\b(chan|buon chan|nham chan|bored|boring)\b")
_STUCK = re.compile(
    r"\b(kho|sai hoai|sai mai|sai hoai sai mai|khong hieu|khong lam duoc|bi ket|stuck|hard|difficult|confus\w*"
    r"|keep (?:failing|getting)|dont (?:get|understand)|cant (?:do|solve|get))\b")
_TOPIC_STRONG = {
    "loops": re.compile(r"\b(vong lap|vong for|loops?|range|while|for loops?|lap lai)\b"),
    "functions": re.compile(r"\b(ham|functions?|def|return|tham so|parameters?|arguments?)\b"),
    "conditions": re.compile(r"\b(dieu kien|conditions?|conditionals?|elif|else)\b"),
    "variables": re.compile(r"\b(bien|variables?|phep gan|assign\w*)\b"),
}
_TOPIC_WEAK = {"conditions": re.compile(r"\b(if)\b")}


# Small talk (all matched on the folded text, so accents and case never matter).
_HOW_ARE_YOU = re.compile(
    r"\b(?:how are (?:you|u)|how r (?:you|u)|hows it going|how is it going|how have you been|how do you do|hows life"
    r"|whats up|ban (?:co )?khoe (?:khong|ko|hok|k)\b|khoe khong|ban (?:co )?on khong|ban the nao|ban sao roi"
    r"|dao nay (?:sao|the nao|ra sao|co khoe|ban sao)|ban dang the nao|ban (?:co )?vui khong)")
_THANKS = re.compile(r"\b(?:thanks?|thank you|thx|cam on|camon)\b")
_GREETING = re.compile(r"\b(?:hi|hello|hey|hiya|howdy|yo|alo|chao|xin chao|good (?:morning|afternoon|evening|day))\b")
_WHAT_TO_PLAY = re.compile(
    r"\b(?:what (?:should|can|do) i (?:play|do|try|practice|practise|start)(?: next| now| today)?"
    r"|what to (?:play|do|try)|whats next|what next|play next|something to (?:play|do|try)"
    r"|suggest (?:me )?(?:something|a game|a level)|recommend\w*|any (?:ideas?|suggestions?)"
    r"|nen (?:choi|lam|luyen)(?: gi)?|choi gi|lam gi (?:tiep|bay gio|nhi|day)|goi y (?:cho minh |bai |man |tro choi )?"
    r"|tiep theo (?:la )?(?:gi|nao)|bai tiep theo)\b")
MAX_GREETING_WORDS = 8   # "hi" inside a long message is rarely a greeting


def _strong_topics(folded: str) -> list[str]:
    return [topic for topic in TOPICS if _TOPIC_STRONG[topic].search(folded)]


def _topic_of(folded: str, mood_word: bool) -> Optional[str]:
    hits = _strong_topics(folded)
    if not hits and not mood_word:
        hits = [t for t, rx in _TOPIC_WEAK.items() if rx.search(folded)]
    return hits[0] if hits else None


def canned_chat(messages: list[dict], context: Optional[dict] = None) -> dict:
    """Rule-based Misaki: ``{"text", "mood", "action"}``. Works with no AI at all (Vietnamese or English by request)."""
    context = context or {}
    level = context.get("level") if context.get("level") in LEVELS else "intermediate"
    last = next((m["text"] for m in reversed(messages) if m.get("role") == "user"), "")
    folded = fold(last)
    bored, stuck = bool(_BORED.search(folded)), bool(_STUCK.search(folded))
    topic = _topic_of(folded, bored or stuck)
    if topic:
        name = topic_name(topic)
        if _PRACTICE.search(folded):
            return {"text": tr(f"Được thôi! Mình mở Luyện tập chủ đề {name} cho bạn nhé.",
                               f"Sure! Let's open Practice on {name}."),
                    "mood": "happy",
                    "action": {"type": "rescue", "mode": "practice", "level": level, "focus_topic": topic}}
        return {"text": tr(f"Chủ đề {name} hả? Mình viết cho bạn một câu đố nhỏ về {name} nhé, bạn chỉ cần bấm nút bên dưới.",
                           f"{name.capitalize()}, right? I can write you a small puzzle about {name}, just press the button below."),
                "mood": "thinking", "action": {"type": "make_puzzle", "topic": topic, "idea": ""}}
    if _WHAT_TO_PLAY.search(folded):
        return _recommendation(context, level)
    if bored:
        return {"text": tr("Chán rồi à? Vậy mình đấu một ván tập với mình cho vui nhé, thua cũng không sao đâu.",
                           "Feeling bored? Let's play a practice match against me, it's just for fun."),
                "mood": "excited", "action": {"type": "pvp_training", "misaki": 1}}
    if stuck:
        return {"text": tr("Ai cũng có lúc bị kẹt, không sao đâu. Mình mở khay luyện tập các lỗi bạn hay sai để ôn lại từng chút nhé.",
                           "Everyone gets stuck sometimes, it's okay. Let's open practice for the mistakes you make most and go over them step by step."),
                "mood": "worried", "action": {"type": "practice_tray"}}
    if _HOW_ARE_YOU.search(folded):
        return _pick(_how_are_you(), messages)
    if _THANKS.search(folded):
        return _pick(_thanks(), messages)
    if _GREETING.search(folded) and len(folded.split()) <= MAX_GREETING_WORDS:
        return _pick(_greetings(), messages)
    return _pick(_catch_all(), messages)


def _recommendation(context: dict, level: str) -> dict:
    """"What should I play next?": one concrete pick from the learner's own context, with an action."""
    weak = next((t for t in (context.get("weak_topics") or []) if t in TOPICS), None)
    if weak:
        name = topic_name(weak)
        return {"text": tr(f"Dạo này bạn hay vướng {name}, nên mình gợi ý luyện tập {name} nhé. Bấm nút bên dưới là vào chơi liền!",
                           f"You've been tripping on {name} lately, so I'd go with some {name} practice. Press the button below to jump in!"),
                "mood": "excited",
                "action": {"type": "rescue", "mode": "practice", "level": level, "focus_topic": weak}}
    if level == "beginner":
        levels = rows.load_levels()
        if levels:
            first = min(levels.values(), key=lambda lv: lv.get("order", 0))
            title = tr(first["title"], first.get("title_en") or first["title"])
            return {"text": tr(f"Bạn mới bắt đầu nên thử Syntax Rows màn \"{title}\" nhé, màn này nhẹ nhàng thôi. Bấm nút bên dưới để chơi!",
                               f"Since you're just starting, try the Syntax Rows level \"{title}\", it's a gentle one. Press the button below to play!"),
                    "mood": "excited", "action": {"type": "rows", "level_id": first["id"]}}
    return {"text": tr("Mình nghĩ bạn nên thử một ván Code Rescue ở đúng trình độ của bạn. Bấm nút bên dưới nhé, mình tin bạn làm được!",
                       "I think a Code Rescue round at your level is just right for you. Press the button below, I believe in you!"),
            "mood": "excited", "action": {"type": "rescue", "mode": "rescue", "level": level, "focus_topic": None}}


def _greetings() -> list[dict]:
    return [
        {"text": tr("Chào bạn! Mình là Misaki, vui quá được gặp bạn. Hôm nay bạn muốn luyện Python hay chơi một ván cho vui?",
                    "Hi there! I'm Misaki, so happy to see you. Do you want to practice some Python today, or play a quick game?"),
         "mood": "happy", "action": None},
        {"text": tr("Xin chào! Mình đang chờ bạn đây. Hôm nay mình cùng giải một câu đố Python nhé, hay bạn đang muốn hỏi gì?",
                    "Hello! I was just waiting for you. Shall we solve a Python puzzle today, or is there something you want to ask?"),
         "mood": "excited", "action": None},
    ]


def _how_are_you() -> list[dict]:
    return [
        {"text": tr("Mình khỏe, nhất là khi có bạn ghé chơi! Mình đang mê giải câu đố lắm. Còn bạn thì sao, hôm nay vui không?",
                    "I'm doing great, especially now that you're here! I'm really into puzzles today. How about you, is your day going well?"),
         "mood": "happy", "action": None},
        {"text": tr("Mình vui lắm, cảm ơn bạn đã hỏi! Hôm nay mình vừa nghĩ ra mấy câu đố hay. Còn bạn khỏe không, có muốn thử một câu không?",
                    "I'm happy, thanks for asking! I just thought up a few fun puzzles today. How are you, want to try one?"),
         "mood": "shy", "action": None},
    ]


def _thanks() -> list[dict]:
    return [
        {"text": tr("Không có gì đâu! Mình luôn sẵn sàng giúp bạn.", "You're welcome! I'm always happy to help."),
         "mood": "happy", "action": None},
        {"text": tr("Hihi, được giúp bạn là mình vui rồi! Cần gì cứ nói nhé.", "Hehe, I'm glad I could help! Just say the word if you need more."),
         "mood": "shy", "action": None},
    ]


def _catch_all() -> list[dict]:
    return [
        {"text": tr("Mình giúp được vài việc: giải thích biến, câu điều kiện, vòng lặp hoặc hàm, viết câu đố riêng cho bạn, "
                    "hoặc gợi ý bài tập khi bạn thấy chán hay bị kẹt. Bạn đang vướng chỗ nào?",
                    "I can help with variables, conditions, loops or functions, write a puzzle just for you, "
                    "or suggest something to play when you're bored or stuck. What's troubling you?"),
         "mood": "happy", "action": None},
        {"text": tr("Hmm, mình chưa hiểu ý bạn lắm. Bạn thử nói về biến, câu điều kiện, vòng lặp hoặc hàm xem, hoặc bảo mình gợi ý một trò để chơi nhé?",
                    "Hmm, I didn't quite get that. Tell me about variables, conditions, loops or functions, or ask me to suggest something to play?"),
         "mood": "thinking", "action": None},
        {"text": tr("Mình giỏi nhất là chuyện Python và các trò trong game này. Bạn muốn mình viết một câu đố nhỏ hay chọn giúp bạn một màn chơi?",
                    "Python and the games here are what I know best. Would you like me to write you a small puzzle, or pick a level for you?"),
         "mood": "neutral", "action": None},
        {"text": tr("Chuyện đó mình chưa giúp được rồi, nhưng về Python thì mình sẵn sàng! Bạn đang muốn tìm hiểu phần nào?",
                    "I can't help with that one, but Python is my thing! Which part would you like to explore?"),
         "mood": "happy", "action": None},
    ]


def _pick(options: list[dict], messages: list[dict]) -> dict:
    """Rotate deterministically through ``options`` (by how many things the learner has said) and never repeat the
    reply Misaki gave last, so the same kind of message does not get the same line twice in a row."""
    user_turns = sum(1 for m in messages if m.get("role") == "user")
    previous = next((m["text"].strip() for m in reversed(messages) if m.get("role") == "misaki"), None)
    start = user_turns % len(options)
    for step in range(len(options)):
        choice = options[(start + step) % len(options)]
        if choice["text"] != previous:
            return choice
    return options[start]


# --------------------------------------------------------------------------- chat flow


_CANNED_REVIEW_QUESTION = re.compile(
    r"\b(?:review|how did i do|what did i get|what (?:did i do|went) wrong|why (?:was|is) (?:my|that|it)|"
    r"which (?:puzzles?|answers?)|on lai|dung va sai|dung o dau|sai o dau|tai sao minh|vi sao minh)\b"
)


def _checked_review(pending: dict) -> list[dict]:
    try:
        puzzles = custom.misaki_puzzles(pending["set_id"])
    except bank.BankError:
        return []
    checked = []
    counts: dict[str, int] = {}
    for attempt in reversed(pending["attempts"]):
        puzzle_id = attempt["puzzle_id"]
        puzzle = puzzles.get(puzzle_id)
        if puzzle is None or counts.get(puzzle_id, 0) >= 2:
            continue
        option_id, order = attempt.get("option_id"), attempt.get("order")
        try:
            result = bank.check_answer(puzzle, option_id=option_id, order=order,
                                       reveal=attempt.get("reveal", False), diagnose=custom.diagnose)
            evidence = bank.attempt_context(puzzle, result, option_id=option_id, order=order)
        except bank.BankError:
            continue
        counts[puzzle_id] = counts.get(puzzle_id, 0) + 1
        checked.append({**evidence, "puzzle_id": puzzle_id, "topic": puzzle["topic"], "correct": result["correct"],
                        "error_group": result["error_group"]})
    return list(reversed(checked))


def _review_reply(review: list[dict]) -> dict:
    right = sum(attempt["correct"] for attempt in review)
    wrong = len(review) - right
    summary = tr(f"Các lượt gần đây: {right} đúng, {wrong} sai.", f"Recent attempts: {right} correct, {wrong} incorrect.")
    details = [summary]
    latest_wrong = next((attempt for attempt in reversed(review) if not attempt["correct"]), None)
    if latest_wrong:
        detail = latest_wrong["reference"] or latest_wrong["diagnosis"]
        if latest_wrong["type"] == "predict_output":
            choice = " · ".join(latest_wrong["choice"].splitlines())
            detail = tr(f"Bạn đoán `{choice}`. ", f"You predicted `{choice}`. ") + detail
        details.append(detail)
    latest_right = next((attempt for attempt in reversed(review) if attempt["correct"]), None)
    if latest_right:
        details.append(tr("Ở lượt đúng gần nhất, bạn đã giải được câu đố. ", "On your latest correct try, you solved it. ")
                       + (latest_right["reference"] or latest_right["diagnosis"]))
    return {"text": clean_text(" ".join(details), MAX_TEXT), "mood": "thinking" if wrong else "happy", "action": None}


def _ai_context(messages: list[dict], context: Optional[dict], review: list[dict]) -> dict:
    ctx = {"messages": [{"role": m["role"], "text": m["text"]} for m in messages],
           "rows_levels": sorted(rows_level_ids())}
    if context:
        ctx["learner"] = {"level": context.get("level"), "weak_topics": list(context.get("weak_topics") or [])}
    if review:
        ctx["puzzle_review"] = review
    return ctx


def chat(messages: list[dict], context: Optional[dict], client: Optional[str], *,
         voice_language: Optional[str] = None) -> dict:
    """``{"text", "source", "mood", "action"}``. The safety check runs first and never calls the tutor."""
    last = messages[-1]["text"]
    if is_crisis(last):
        return safety_reply()
    context = context or {}
    folded = fold(last)
    configured = tutor.configured()
    pending = context.get("puzzle_review")
    puzzle_request = context.get("puzzle_request")
    follow_up = puzzle_request == "follow_up"
    wants_review = bool(puzzle_request or (pending and _CANNED_REVIEW_QUESTION.search(folded)))
    review = _checked_review(pending) if pending and (configured or wants_review) else []
    review_topic = review[-1]["topic"] if review else None
    if wants_review and not review:
        canned = {"text": tr("Mình chưa tìm thấy lượt làm đã chấm. Bạn thử trả lời một câu đố mới của mình nhé.",
                             "I couldn't find a checked attempt. Try answering one of my new puzzles first."),
                  "mood": "thinking", "action": None}
        if puzzle_request:
            return {**canned, "source": "canned"}
    elif follow_up:
        canned = {"text": tr("Thử thêm một câu cùng chủ đề nhé.", "Try one more puzzle on the same idea."),
                  "mood": "thinking", "action": {"type": "make_puzzle", "topic": review_topic, "idea": ""}}
    else:
        canned = _review_reply(review) if wants_review else canned_chat(messages, context)
    if not configured:
        return {**canned, "source": "canned"}
    previous_action = None
    if len(messages) > 1 and messages[-2]["role"] == "misaki":
        previous_action = validate_action(context.get("previous_action"))
    ai_context = _ai_context(messages, context, review)
    if voice_language:
        ai_context["voice_language"] = voice_language
    if previous_action:
        ai_context["previous_action"] = previous_action
    if puzzle_request:
        ai_context["puzzle_request"] = puzzle_request
    topics = _strong_topics(folded)
    requested_topic = review_topic if follow_up else topics[0] if len(topics) == 1 else None
    validate = partial(validate_chat_reply, requested_topic=requested_topic, follow_up=follow_up,
                       previous_action=previous_action, review_topic=review_topic, voice_language=voice_language)
    return tutor.ask_json(tutor_prompts.CHAT_TASK, ai_context, canned, validate, client=client)


# --------------------------------------------------------------------------- puzzle flow (spec section 2)

# Two authored programs per topic. Each one was run through custom.create_set (tests/test_misaki_chat.py does it again
# on every run) and yields puzzles; infer_topic gives the topic they are filed under.
AUTHORED: dict[str, list[str]] = {
    "variables": [
        "price = 12\ncount = 3\ntotal = price * count\nprint(total)",
        "a = 7\nb = 4\na = a + b\nb = a - b\nprint(a, b)",
    ],
    "conditions": [
        "score = 7\nif score >= 5:\n    print(score * 2)\nelse:\n    print(score + 1)",
        "temp = 28\nif temp > 30:\n    print(1)\nelif temp > 20:\n    print(2)\nelse:\n    print(3)",
    ],
    "loops": [
        "total = 0\nfor i in range(1, 5):\n    total = total + i\nprint(total)",
        "count = 0\nfor n in range(2, 8):\n    if n % 2 == 0:\n        count = count + 1\nprint(count)",
    ],
    "functions": [
        "def double(x):\n    return x * 2\nprint(double(6))",
        "def area(w, h):\n    return w * h\nprint(area(3, 5) + 1)",
    ],
}


def _canned_note(topic: str) -> str:
    name = topic_name(topic)
    return tr(f"Mình viết sẵn một chương trình nhỏ về {name}. Thử đoán xem nó làm gì nhé!",
              f"I wrote a small program about {name} for you. Try to work out what it does!")


def _is_rate_limit(exc: Exception) -> bool:
    return isinstance(exc, custom.CustomError) and exc.status == 429


def make_puzzle(topic: str, idea: str, level: str, client: Optional[str], *,
                voice_language: Optional[str] = None) -> dict:
    """``{"set", "source": "ai" | "canned", "note"}``. A 429 from the custom-set rate limit passes through."""
    if tutor.configured():
        context = {"topic": topic, "idea": idea, "level": level}
        if voice_language:
            context["voice_language"] = voice_language
        reply = tutor.ask_json("misaki_puzzle", context, {"code": "", "note": ""},
                               partial(validate_puzzle_reply, voice_language=voice_language), client=client)
        if reply["source"] == "ai":
            try:
                made = custom.create_set(reply["code"], level, client, from_misaki=True)
            except custom.CustomError as exc:
                if _is_rate_limit(exc):
                    raise
                logger.info("misaki puzzle: AI program rejected (%s)", exc.status)
            except Exception as exc:  # the sandbox must never take the endpoint down: use an authored program
                logger.warning("misaki puzzle: AI program failed (%s)", type(exc).__name__)
            else:
                result = {"set": made, "source": "ai", "note": reply["note"] or _canned_note(topic)}
                if "speech_text" in reply:
                    result["speech_text"] = reply["speech_text"]
                return result
    programs = AUTHORED[topic][:]
    random.shuffle(programs)
    last: Optional[Exception] = None
    for code in programs:
        try:
            return {"set": custom.create_set(code, level, client, from_misaki=True),
                    "source": "canned", "note": _canned_note(topic)}
        except custom.CustomError as exc:
            if _is_rate_limit(exc):
                raise
            last = exc
    raise custom.CustomError(
        tr("Misaki chưa nghĩ ra câu đố nào lúc này. Bạn thử lại sau nhé.",
           "Misaki couldn't come up with a puzzle right now. Please try again later."), 503) from last
