"""Opt-in speech for a Misaki reply the server has already issued."""
import base64
import hmac
import os
import time

from . import tutor, tutor_prompts

MAX_SPEECH = 600
MAX_WAV_BYTES = 3_000_000
TICKET_TTL = 4 * 60 * 60


def _key() -> bytes:
    name = "SYNTAX_STACK_TUTOR_TOKEN" if tutor.provider() == "n8n" else "SYNTAX_STACK_GEMINI_API_KEY"
    return os.getenv(name, "").encode()


def _signature(key: bytes, payload: str) -> str:
    return hmac.digest(key, b"misaki-voice:" + payload.encode(), "sha256").hex()


def issue(text: str) -> dict | None:
    key = _key()
    text = text.replace("`", "").strip()[:MAX_SPEECH]
    if not key or not text or tutor.daily_limit() == 0:
        return None
    expires = int(time.time()) + TICKET_TTL
    transcript = base64.urlsafe_b64encode(text.encode()).decode()
    payload = f"{expires}.{transcript}"
    return {"ticket": f"{payload}.{_signature(key, payload)}", "expires": expires}


def read_ticket(ticket: str) -> str | None:
    key = _key()
    payload, sep, signature = ticket.rpartition(".")
    if not key or not sep or not signature.isascii() or not hmac.compare_digest(signature, _signature(key, payload)):
        return None
    expires, transcript = payload.split(".", 1)
    if int(expires) <= time.time():
        return None
    return base64.urlsafe_b64decode(transcript).decode()


def _validate_wave(raw: dict) -> dict:
    encoded = raw.get("audio")
    if not isinstance(encoded, str) or len(encoded) > 4 * ((MAX_WAV_BYTES + 2) // 3):
        raise ValueError("Invalid speech payload")
    wav = base64.b64decode(encoded, validate=True)
    if not wav.startswith(b"RIFF") or wav[8:12] != b"WAVE" or len(wav) <= 44 or len(wav) > MAX_WAV_BYTES:
        raise ValueError("Invalid speech WAV")
    return {"wav": wav}


def synthesize(text: str, client: str | None) -> bytes | None:
    reply = tutor.ask_json(tutor_prompts.VOICE_TASK, {"text": text}, {}, _validate_wave, client=client, cache=False)
    return reply.get("wav")
