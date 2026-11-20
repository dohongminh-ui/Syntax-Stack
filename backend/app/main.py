"""Syntax Stack backend: FastAPI app. API under /api, static frontend at / (if ../frontend exists)."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Annotated, Any, Literal, Optional

from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException, Query, Request, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, StringConstraints, model_validator

from . import bank, custom, hints, i18n, misaki, nicknames, pvp, ranked, rescue_engine, rooms, rows, tutor
from . import validator as V
from .i18n import tr

if sys.version_info < (3, 12):  # the validator reads ast node.type_params (3.12+)
    raise RuntimeError(
        f"Syntax Stack needs Python 3.12 or newer; this is {sys.version.split()[0]}.")

# The interactive API docs (/docs, /redoc, /openapi.json) are a free map of the API, so they are off
# unless SYNTAX_STACK_API_DOCS=1 (handy locally).
_DOCS = os.getenv("SYNTAX_STACK_API_DOCS", "").strip() in ("1", "true", "yes")
@asynccontextmanager
async def _lifespan(_app):
    yield
    pvp.shutdown()  # a deploy / restart ends every live 1v1 match (reason server_restart, no rating change)


app = FastAPI(title="Syntax Stack API", version="1.0", lifespan=_lifespan,
              docs_url="/docs" if _DOCS else None, redoc_url="/redoc" if _DOCS else None,
              openapi_url="/openapi.json" if _DOCS else None)

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^http://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_methods=["*"],
    allow_headers=["*"],
)

# Largest request body accepted. Real requests are a few KB (the biggest is a Code Rescue
# /next with every puzzle seen this game); without a limit a single 100 MB body would be parsed
# into memory before validation even starts.
MAX_BODY_BYTES = 64 * 1024
# A ranked run's move list (up to 3000 moves, ~35 bytes each) is the one legitimately big body.
MAX_FINISH_BODY_BYTES = 192 * 1024
_FINISH_PATH = re.compile(r"^/api/runs/[0-9a-f]{16}/finish$")


class _BodyLimit:
    """Pure ASGI middleware: 413 for a declared Content-Length over the limit; a body streamed
    without one is cut off at the limit (FastAPI then answers 400)."""

    def __init__(self, app, limit: int):
        self.app, self.limit = app, limit

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] in ("GET", "HEAD", "OPTIONS"):
            return await self.app(scope, receive, send)
        limit = MAX_FINISH_BODY_BYTES if _FINISH_PATH.match(scope.get("path", "")) else self.limit
        declared = dict(scope.get("headers") or []).get(b"content-length", b"")
        if declared.isdigit() and int(declared) > limit:
            response = JSONResponse({"detail": tr("Yêu cầu quá lớn.", "The request is too large.")}, status_code=413)
            return await response(scope, receive, send)
        seen = 0

        async def limited():
            nonlocal seen
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body", b""))
                if seen > limit:
                    raise ValueError("request body over the size limit")
            return message

        return await self.app(scope, limited, send)


app.add_middleware(_BodyLimit, limit=MAX_BODY_BYTES)  # added last = runs first
# Language of the request (header ``X-Lang: en|vi``, default vi) for every message built while it is served; the
# outermost middleware, so the 413 above is localized too. See app/i18n.py.
app.add_middleware(i18n.LangMiddleware)


def _client_ip(request: Request) -> Optional[str]:
    """The visitor's IP: Cloudflare's CF-Connecting-IP when present, else the direct peer."""
    return request.headers.get("cf-connecting-ip") or (request.client.host if request.client else None)


# Cache policy for responses that pass through a CDN (Cloudflare caches .css/.js by default and
# otherwise falls back to its own 4-hour TTL). The frontend's files have fixed names and the JS
# modules import each other by plain relative paths, so a long cache would serve old CSS next to
# new JS after a deploy. Code and pages therefore revalidate every time (cheap: StaticFiles answers
# a matching ETag with 304); images and icons change rarely and may be cached for a day.
_REVALIDATE = (".html", ".css", ".js", ".json", ".xml", ".txt")
_CACHE_A_DAY = (".png", ".ico", ".svg")


# Browser hardening sent on every response. The page itself also gets a Content-Security-Policy
# (see _index), which needs the import map's hash.
_SECURITY_HEADERS = {
    "Strict-Transport-Security": "max-age=31536000",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
}


@app.middleware("http")
async def _cache_headers(request, call_next):
    response = await call_next(request)
    for name, value in _SECURITY_HEADERS.items():
        response.headers.setdefault(name, value)
    path = request.url.path
    if path.startswith("/api/"):
        response.headers.setdefault("Cache-Control", "no-store")
    elif request.query_params.get("v") and path.endswith((".css", ".js")) and response.status_code == 200:
        # versioned by render_index(): the URL changes on every deploy, so cache it for good
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    elif path == "/" or path.endswith(_REVALIDATE):
        response.headers["Cache-Control"] = "no-cache"
    elif path.endswith(_CACHE_A_DAY):
        response.headers["Cache-Control"] = "public, max-age=86400"
    return response


@app.exception_handler(bank.BankError)
async def _bank_error(_, exc: bank.BankError):
    return JSONResponse({"detail": str(exc)}, status_code=exc.status)


@app.exception_handler(rows.RowsError)
async def _rows_error(_, exc: rows.RowsError):
    return JSONResponse({"detail": str(exc)}, status_code=422)


@app.exception_handler(rows.LevelNotFound)
async def _level_not_found(_, exc: rows.LevelNotFound):
    return JSONResponse({"detail": exc.args[0]}, status_code=404)


# --------------------------------------------------------------------------- models

Topic = Literal["variables", "conditions", "loops", "functions"]
Level = Literal["beginner", "intermediate", "advanced"]
Kind = Literal["rescue", "debug", "last_commit"]


class NextRequest(BaseModel):
    topic: Optional[Topic] = None
    tier: Optional[Literal[1, 2, 3]] = None
    level: Level = "intermediate"
    kind: Kind = "rescue"
    template_id: Optional[str] = Field(default=None, max_length=80)
    # list caps: far above real play (a game sees well under 200 puzzles; the client sends the last 500)
    exclude_ids: list[str] = Field(default_factory=list, max_length=1000)
    exclude_templates: list[str] = Field(default_factory=list, max_length=50)
    # Ranked run / race: with a valid pair the server picks the puzzle deterministically and records it.
    run_id: Optional[str] = Field(default=None, max_length=32)
    run_token: Optional[str] = Field(default=None, max_length=64)
    # Live 1v1 match (docs/pvp.md): with a valid pair the server picks the puzzle for the player's current lock, or for
    # the bug line `bug` (its id in the player's bugLines) when kind is "debug".
    match_id: Optional[str] = Field(default=None, max_length=32)
    match_token: Optional[str] = Field(default=None, max_length=64)
    bug: Optional[int] = Field(default=None, ge=1, le=1_000_000)


class CustomSetRequest(BaseModel):
    # No length cap here: too long must be a 422 from custom.create_set (in the request's language), not a pydantic list.
    code: str
    level: Level = "intermediate"


class MisakiMessage(BaseModel):
    role: Literal["user", "misaki"]
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


class OrderItem(BaseModel):
    line_id: str = Field(max_length=40)
    indent: int


class MisakiAttempt(BaseModel):
    puzzle_id: str = Field(max_length=20)
    option_id: Optional[str] = Field(default=None, max_length=40)
    order: Optional[list[OrderItem]] = Field(default=None, max_length=30)
    reveal: bool = False


class MisakiPuzzleReview(BaseModel):
    set_id: str = Field(pattern=r"^[a-z2-7]{8}$")
    attempts: list[MisakiAttempt] = Field(min_length=1, max_length=misaki.MAX_REVIEW_ATTEMPTS)


class MisakiContext(BaseModel):
    level: Optional[Level] = None
    weak_topics: list[Topic] = Field(default_factory=list, max_length=4)
    puzzle_review: Optional[MisakiPuzzleReview] = None


class MisakiChatRequest(BaseModel):
    messages: list[MisakiMessage] = Field(min_length=1, max_length=12)
    context: Optional[MisakiContext] = None

    @model_validator(mode="after")
    def _last_is_user(self):
        if self.messages[-1].role != "user":
            raise ValueError("the last message must be from the user")
        return self


class MisakiPuzzleRequest(BaseModel):
    topic: Topic
    idea: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] = ""
    level: Level = "intermediate"


class AnswerRequest(BaseModel):
    option_id: Optional[str] = Field(default=None, max_length=40)
    order: Optional[list[OrderItem]] = Field(default=None, max_length=30)
    line_id: Optional[str] = Field(default=None, max_length=40)
    reveal: bool = False
    # Live classroom: when both are valid the server logs the checked result for the teacher dashboard.
    room: Optional[str] = Field(default=None, max_length=16)
    player_token: Optional[str] = Field(default=None, max_length=64)
    # Ranked run / race: when both are valid the server records the checked result for the replay.
    run_id: Optional[str] = Field(default=None, max_length=32)
    run_token: Optional[str] = Field(default=None, max_length=64)
    # Live 1v1 match: when both are valid the checked result is applied to the player's game.
    match_id: Optional[str] = Field(default=None, max_length=32)
    match_token: Optional[str] = Field(default=None, max_length=64)


class RoomCreateRequest(BaseModel):
    level: Level = "intermediate"
    title: Optional[str] = Field(default=None, max_length=200)  # real limit (40) is a 422 in rooms.py
    names: Literal["random", "free"] = "random"


class RoomJoinRequest(BaseModel):
    # Ignored in "random" rooms; in "free" rooms the real limit (20) is a 422 in rooms.py
    nickname: Optional[str] = Field(default=None, max_length=200)


class RoomProgressRequest(BaseModel):
    player_token: str = Field(max_length=64)
    score: int = Field(ge=0, le=10_000_000)
    status: Literal["playing", "crash", "nofit"]
    bugs_fixed: int = Field(ge=0, le=1_000_000)


class TokenPlacement(BaseModel):
    id: str = Field(max_length=40)
    col: int


class RowPlacement(BaseModel):
    row: int
    tokens: list[TokenPlacement] = Field(default_factory=list, max_length=30)


class RunRequest(BaseModel):
    rows: list[RowPlacement] = Field(default_factory=list, max_length=30)
    trace: bool = False
    prediction: Optional[str] = Field(default=None, max_length=240)


class RowsHintRequest(RunRequest):
    trace_step: Optional[int] = Field(default=None, ge=0)


class RowsTwistRequest(RunRequest):
    baseline: list[RowPlacement] = Field(max_length=30)


class TeachBackRequest(RunRequest):
    reflection: str = Field(min_length=1, max_length=400)


class WrongAttempt(BaseModel):
    puzzle_id: str = Field(max_length=80)
    kind: Kind
    option_id: Optional[str] = Field(default=None, max_length=40)
    order: Optional[list[OrderItem]] = Field(default=None, max_length=30)
    line_id: Optional[str] = Field(default=None, max_length=40)


class DebriefRequest(BaseModel):
    level: Level
    mode: Literal["rescue", "practice"]
    end_reason: Literal["crash", "nofit"]
    wrong: list[WrongAttempt] = Field(min_length=1, max_length=12)


class RunCreateRequest(BaseModel):
    kind: Literal["ranked", "race"]
    level: Optional[Level] = None  # required for "ranked"; a race brings its own level
    nickname: str = Field(max_length=200)  # real limit (20) is a 422 in rooms.py
    device_id: str = Field(max_length=64)
    race: Optional[str] = Field(default=None, max_length=16)


class RunFinishRequest(BaseModel):
    run_token: str = Field(max_length=64)
    # Entries are checked by the replay (a malformed move makes the run "rejected"); only the size is bounded here.
    moves: list[dict[str, Any]] = Field(max_length=rescue_engine.MAX_MOVES)
    client_score: Optional[int] = Field(default=None, ge=0, le=10_000_000)  # logged only, never trusted


class RaceCreateRequest(BaseModel):
    level: Level
    nickname: str = Field(max_length=200)
    device_id: str = Field(max_length=64)


class PvpStartRequest(BaseModel):
    level: Level
    nickname: str = Field(max_length=200)  # real rule: a generated name (422 in ranked._clean_identity)
    device_id: str = Field(max_length=64)


class PvpBotRequest(PvpStartRequest):
    misaki: Optional[int] = Field(default=None, ge=1, le=4)   # Misaki's ladder level (docs/pvp.md section 5)
    training: bool = False


class PvpJoinRequest(BaseModel):
    nickname: str = Field(max_length=200)
    device_id: str = Field(max_length=64)


# Topic names, as the frontend shows them (frontend/js/pieces.js: TOPIC_NAMES).
TOPIC_NAMES_VI = {"variables": "Biến", "conditions": "Điều kiện", "loops": "Vòng lặp", "functions": "Hàm"}
TOPIC_NAMES_EN = {"variables": "Variables", "conditions": "Conditions", "loops": "Loops", "functions": "Functions"}
PREDICT_TRACE_STEPS = 40


# --------------------------------------------------------------------------- Code Rescue


@app.get("/api/health")
def health():
    return {"ok": True, "puzzles": bank.count_puzzles(), "tutor": tutor.stats()}


@app.post("/api/puzzle/next")
def puzzle_next(req: NextRequest):
    if req.kind == "debug":
        if not req.template_id:
            raise HTTPException(422, tr("kind 'debug' cần có template_id.", "kind 'debug' needs a template_id."))
    elif req.kind == "rescue" and (req.topic is None or req.tier is None):
        raise HTTPException(422, tr("kind 'rescue' cần có topic và tier.", "kind 'rescue' needs a topic and a tier."))
    live = pvp.serve_puzzle(req.match_id, req.match_token, kind=req.kind, bug=req.bug, topic=req.topic,
                            template_id=req.template_id)
    if live is not None:  # a valid live match: the server picked the puzzle for the player's lock / bug line
        row, level = live
        return bank.public_puzzle(row, level)
    run = ranked.serve_puzzle(req.run_id, req.run_token, kind=req.kind, topic=req.topic, tier=req.tier,
                              template_id=req.template_id)
    if run is not None:  # a valid ranked run / race: deterministic pick, already recorded
        row, level = run
        return bank.public_puzzle(row, level)
    row = bank.select_puzzle(
        kind=req.kind, topic=req.topic, tier=req.tier, level=req.level, template_id=req.template_id,
        exclude_ids=req.exclude_ids, exclude_templates=req.exclude_templates)
    return bank.public_puzzle(row, req.level)


def _get_puzzle(puzzle_id: str) -> dict:
    """Bank puzzle, or a custom one (ids ``c-<set>-<n>``)."""
    return custom.get_puzzle(puzzle_id) if custom.is_custom_id(puzzle_id) else bank.get_puzzle(puzzle_id)


def _diagnoser(puzzle_id: str):
    """Custom puzzles run their parsons check in the sandbox child process, never in this process."""
    return custom.diagnose if custom.is_custom_id(puzzle_id) else None


@app.post("/api/puzzle/{puzzle_id}/answer")
def puzzle_answer(puzzle_id: str, req: AnswerRequest):
    row = _get_puzzle(puzzle_id)
    result = bank.check_answer(
        row, option_id=req.option_id,
        order=[o.model_dump() for o in req.order] if req.order is not None else None,
        line_id=req.line_id, reveal=req.reveal, diagnose=_diagnoser(puzzle_id))
    if req.room and req.player_token and not custom.is_custom_id(puzzle_id):
        rooms.log_answer(req.room, req.player_token, row, req.option_id, result)  # never raises
    if req.run_id and req.run_token and not custom.is_custom_id(puzzle_id):
        ranked.record_answer(req.run_id, req.run_token, puzzle_id, result["correct"])  # never raises
    if req.match_id and req.match_token and not custom.is_custom_id(puzzle_id):
        pvp.record_answer(req.match_id, req.match_token, puzzle_id, result["correct"])  # never raises
    return result


@app.get("/api/puzzle/{puzzle_id}/hint")
def puzzle_hint(puzzle_id: str, level: int = Query(..., ge=1, le=3),
                run_id: Optional[str] = Query(default=None, max_length=32),
                run_token: Optional[str] = Query(default=None, max_length=64),
                match_id: Optional[str] = Query(default=None, max_length=32),
                match_token: Optional[str] = Query(default=None, max_length=64)):
    hint = hints.puzzle_hint(_get_puzzle(puzzle_id), level)
    if run_id and run_token and not custom.is_custom_id(puzzle_id):
        ranked.record_hint(run_id, run_token, puzzle_id, level)  # never raises
    if match_id and match_token and not custom.is_custom_id(puzzle_id):
        pvp.record_hint(match_id, match_token, puzzle_id, level)  # never raises
    return hint


@app.post("/api/puzzle/{puzzle_id}/explain")
def puzzle_explain(puzzle_id: str, req: AnswerRequest, request: Request):
    puzzle = _get_puzzle(puzzle_id)
    order = [item.model_dump() for item in req.order] if req.order is not None else None
    result = bank.check_answer(puzzle, option_id=req.option_id, order=order, reveal=True,
                               diagnose=_diagnoser(puzzle_id))
    if result["correct"]:
        raise HTTPException(422, tr("Câu trả lời này đã đúng.", "This answer is already correct."))
    evidence = bank.attempt_context(puzzle, result, option_id=req.option_id, order=order)
    return tutor.feedback("explain", evidence, result["explanation"] or result["message"],
                          client=_client_ip(request))


@app.get("/api/puzzle/{puzzle_id}/rematch")
def puzzle_rematch(puzzle_id: str, request: Request, level: Level = "intermediate"):
    if custom.is_custom_id(puzzle_id):
        raise HTTPException(422, tr("Câu đố tự tạo không có bản luyện lại.", "Custom puzzles have no rematch."))
    original = bank.get_puzzle(puzzle_id)
    followup = bank.select_puzzle(
        kind="rescue", topic=original["topic"], tier=original["tier"], level=level,
        template_id=original["template_id"], exclude_ids=[original["id"]], exclude_templates=[],
    )
    intro = tutor.feedback("rematch", {
        "previous_prompt": i18n.pick(original, "prompt"), "next_prompt": i18n.pick(followup, "prompt"),
        "topic": original["topic"], "hint": i18n.pick(followup, "hints")[0],
    }, tr("Thử áp dụng lại quy tắc vừa gặp vào câu đố mới này.",
          "Try applying the rule you just met to this new puzzle."), client=_client_ip(request))
    return {**intro, "puzzle": bank.public_puzzle(followup, level)}


@app.post("/api/rescue/debrief")
def rescue_debrief(req: DebriefRequest, request: Request):
    """End-of-run summary. Everything in the context comes from the bank; the client sends ids only."""
    mistakes: list[dict] = []
    for item in req.wrong:
        try:
            puzzle = bank.get_puzzle(item.puzzle_id)
        except bank.NotFound:
            continue  # unknown ids are skipped silently
        diagnosis = None
        if item.option_id is not None or item.order is not None or item.line_id is not None:
            try:
                result = bank.check_answer(
                    puzzle, option_id=item.option_id, line_id=item.line_id, reveal=True,
                    order=[o.model_dump() for o in item.order] if item.order is not None else None)
                if not result["correct"]:
                    diagnosis = result["message"]
            except bank.BankError:
                pass  # an invalid attempt only loses its diagnosis
        mistakes.append({"topic": puzzle["topic"], "type": puzzle["type"],
                         "template_id": puzzle["template_id"], "prompt": i18n.pick(puzzle, "prompt"),
                         "diagnosis": diagnosis})
    if not mistakes:
        raise HTTPException(422, tr("Không có lỗi nào để tổng kết.", "There are no mistakes to sum up."))
    topic_counts: dict[str, int] = {}
    for m in mistakes:
        topic_counts[m["topic"]] = topic_counts.get(m["topic"], 0) + 1
    focus_topic = max(topic_counts, key=topic_counts.get)  # ties: first in order of appearance
    count = topic_counts[focus_topic]
    fallback = tr(
        f"Ván này bạn sai nhiều nhất ở chủ đề {TOPIC_NAMES_VI.get(focus_topic, focus_topic)} ({count} lần). "
        "Hãy chơi Luyện tập chủ đề này để quen lại quy tắc trước ván sau.",
        f"In this game you made the most mistakes in {TOPIC_NAMES_EN.get(focus_topic, focus_topic)} "
        f"({count} time{'' if count == 1 else 's'}). "
        "Play Practice on this topic to get used to the rule again before your next game.")
    if req.end_reason == "crash":
        fallback += tr(" Nhớ rằng hai câu trả lời sai sẽ kết thúc một ván Code Rescue.",
                       " Remember that two wrong answers end a Code Rescue game.")
    context = {"level": req.level, "mode": req.mode, "end_reason": req.end_reason,
               "topic_counts": topic_counts, "focus_topic": focus_topic, "mistakes": mistakes}
    reply = tutor.feedback("debrief", context, fallback, client=_client_ip(request))
    return {**reply, "focus_topic": focus_topic}


# --------------------------------------------------------------------------- custom puzzle sets


@app.post("/api/custom/sets")
def custom_create(req: CustomSetRequest, request: Request):
    return custom.create_set(req.code, req.level, _client_ip(request))


@app.get("/api/custom/sets/{set_id}")
def custom_get(set_id: str, level: Level = "intermediate"):
    return custom.get_set(set_id, level)


# --------------------------------------------------------------------------- Chat with Misaki (docs/misaki-chat.md)


@app.post("/api/misaki/chat")
def misaki_chat(req: MisakiChatRequest, request: Request):
    """A reply from Misaki: ``{text, source: ai|canned|safety, mood, action}``. Nothing is stored or logged."""
    return misaki.chat([m.model_dump() for m in req.messages],
                       req.context.model_dump() if req.context else None, _client_ip(request))


@app.post("/api/misaki/puzzle")
def misaki_puzzle(req: MisakiPuzzleRequest, request: Request):
    """A custom puzzle set that Misaki wrote (or an authored one): ``{set, source: ai|canned, note}``."""
    return misaki.make_puzzle(req.topic, req.idea, req.level, _client_ip(request))


# --------------------------------------------------------------------------- live classroom


def _join_url(request: Request, code: str) -> str:
    return rooms.join_url(code, headers=request.headers, scheme=request.url.scheme,
                          netloc=request.url.netloc)


@app.post("/api/rooms")
def rooms_create(req: RoomCreateRequest, request: Request):
    made = rooms.create_room(req.level, req.title, _client_ip(request), req.names)
    return {**made, "join_url": _join_url(request, made["code"])}


@app.get("/api/rooms/{code}")
def rooms_get(code: str):
    return rooms.room_info(code)


@app.post("/api/rooms/{code}/join")
def rooms_join(code: str, req: RoomJoinRequest):
    return rooms.join_room(code, req.nickname)


@app.post("/api/rooms/{code}/players/{player_id}/kick", status_code=204)
def rooms_kick(code: str, player_id: str, x_teacher_key: Optional[str] = Header(default=None)):
    rooms.kick_player(code, player_id, x_teacher_key)
    return Response(status_code=204)


@app.post("/api/rooms/{code}/progress", status_code=204)
def rooms_progress(code: str, req: RoomProgressRequest):
    rooms.record_progress(code, req.player_token, req.score, req.status, req.bugs_fixed)
    return Response(status_code=204)


@app.get("/api/rooms/{code}/summary")
def rooms_summary(code: str, x_teacher_key: Optional[str] = Header(default=None)):
    return rooms.summary(code, x_teacher_key)


@app.post("/api/rooms/{code}/close")
def rooms_close(code: str, x_teacher_key: Optional[str] = Header(default=None)):
    return rooms.close_room(code, x_teacher_key)


@app.delete("/api/rooms/{code}", status_code=204)
def rooms_delete(code: str, x_teacher_key: Optional[str] = Header(default=None)):
    rooms.delete_room(code, x_teacher_key)
    return Response(status_code=204)


@app.get("/api/rooms/{code}/qr.svg")
def rooms_qr(code: str, request: Request):
    info = rooms.room_info(code)
    svg = rooms.qr_svg(_join_url(request, info["code"]))
    return Response(svg, media_type="image/svg+xml", headers={"Cache-Control": "private, max-age=300"})


# --------------------------------------------------------------------------- ranked runs and races


@app.get("/api/nickname")
def nickname_new(request: Request):
    """A fresh generated nickname; 60 per minute per client IP."""
    ranked.take_nickname_slot(_client_ip(request))
    return {"nickname": nicknames.generate()}


@app.post("/api/runs")
def runs_create(req: RunCreateRequest, request: Request):
    return ranked.create_run(req.kind, req.level, req.nickname, req.device_id, req.race, _client_ip(request))


@app.post("/api/runs/{run_id}/finish")
def runs_finish(run_id: str, req: RunFinishRequest):
    return ranked.finish_run(run_id, req.run_token, req.moves, req.client_score)


@app.get("/api/leaderboard")
def leaderboard(level: Level, period: Literal["day", "week", "all"] = "all",
                device_id: Optional[str] = Query(default=None, max_length=64)):
    return ranked.leaderboard(level, period, device_id)


@app.post("/api/races")
def races_create(req: RaceCreateRequest, request: Request):
    made = ranked.create_race(req.level, req.nickname, req.device_id, _client_ip(request))
    base = rooms.public_base(headers=request.headers, scheme=request.url.scheme, netloc=request.url.netloc)
    return {**made, "url": f"{base}/?race={made['code']}"}


@app.get("/api/races/{code}")
def races_get(code: str, device_id: Optional[str] = Query(default=None, max_length=64)):
    return ranked.race_info(code, device_id)


# --------------------------------------------------------------------------- real-time 1v1 (docs/pvp.md)


@app.post("/api/pvp/queue")
def pvp_queue(req: PvpStartRequest, request: Request):
    return pvp.queue_join(req.level, req.nickname, req.device_id, _client_ip(request))


@app.delete("/api/pvp/queue/{ticket}", status_code=204)
def pvp_queue_leave(ticket: str):
    pvp.queue_leave(ticket)
    return Response(status_code=204)


@app.post("/api/pvp/private")
def pvp_private(req: PvpStartRequest, request: Request):
    made = pvp.private_create(req.level, req.nickname, req.device_id, _client_ip(request))
    base = rooms.public_base(headers=request.headers, scheme=request.url.scheme, netloc=request.url.netloc)
    return {**made, "url": f"{base}/?duel={made['code']}"}


@app.post("/api/pvp/private/{code}/join")
def pvp_private_join(code: str, req: PvpJoinRequest, request: Request):
    return pvp.private_join(code, req.nickname, req.device_id, _client_ip(request))


@app.post("/api/pvp/bot")
def pvp_bot_match(req: PvpBotRequest, request: Request):
    return pvp.bot_start(req.level, req.nickname, req.device_id, _client_ip(request), req.misaki, req.training)


@app.get("/api/pvp/misaki")
def pvp_misaki(device_id: str = Query(default="", max_length=64)):
    return pvp.misaki_status(device_id)


@app.websocket("/api/pvp/ws")
async def pvp_ws(ws: WebSocket, ticket: str = Query(default="", max_length=64),
                 lang: Optional[str] = Query(default=None, max_length=8)):
    """``?ticket=...&lang=en|vi``: ``lang`` is this player's display language (per connection; missing = ``vi``)."""
    await pvp.serve_socket(ws, ticket, lang)


# --------------------------------------------------------------------------- Syntax Rows


@app.get("/api/rows/levels")
def rows_levels():
    return rows.list_levels()


@app.get("/api/rows/levels/{level_id}")
def rows_level(level_id: str):
    return rows.public_level(rows.get_level(level_id))


@app.post("/api/rows/levels/{level_id}/run")
def rows_run(level_id: str, req: RunRequest):
    lv = rows.get_level(level_id)
    return rows.run_level(lv, [r.model_dump() for r in req.rows], include_trace=req.trace,
                          prediction=req.prediction)


@app.get("/api/rows/levels/{level_id}/practice")
def rows_practice(level_id: str):
    return {"rows": rows.practice_rows(rows.get_level(level_id))}


@app.post("/api/rows/levels/{level_id}/twist")
def rows_twist(level_id: str, req: RowsTwistRequest):
    lv = rows.get_level(level_id)
    return rows.run_twist(lv, [r.model_dump() for r in req.baseline],
                          [r.model_dump() for r in req.rows], include_trace=req.trace)


@app.post("/api/rows/levels/{level_id}/teach-back")
def rows_teach_back(level_id: str, req: TeachBackRequest, request: Request):
    lv = rows.get_level(level_id)
    reflection = req.reflection.strip()
    if not reflection:
        raise HTTPException(422, tr("Hãy viết lời giải thích của bạn.", "Please write your explanation."))
    result = rows.run_level(lv, [r.model_dump() for r in req.rows])
    if not result["passed"]:
        raise HTTPException(422, tr("Hãy hoàn thành màn trước khi giải thích.",
                                    "Finish the level before you explain it."))
    return tutor.feedback("teach_back", {
        "goal": i18n.pick(lv, "goal"), "code": result["code"], "output": result["actual_output"],
        "learner_explanation": reflection,
    }, tr("Nếu đổi đúng một mảnh mã, đầu ra sẽ thay đổi thế nào? / What would change in the output if you swapped one tile?",
          "What would change in the output if you swapped one tile?"),
        client=_client_ip(request))


@app.post("/api/rows/levels/{level_id}/explain-prediction")
def rows_explain_prediction(level_id: str, req: RunRequest, request: Request):
    """Explain a wrong output prediction. The server re-runs the board; the client sends its guess."""
    lv = rows.get_level(level_id)
    prediction = (req.prediction or "").strip()
    if not prediction:
        raise HTTPException(422, tr("Hãy nhập dự đoán của bạn.", "Please enter your prediction."))
    result = rows.run_level(lv, [r.model_dump() for r in req.rows], include_trace=True,
                            prediction=prediction)
    verdict = result["prediction"]["correct"]
    if verdict is None or result["actual_output"] is None:
        raise HTTPException(422, tr("Chương trình chưa chạy xong để đối chiếu dự đoán.",
                                    "The program did not finish running, so the prediction can't be checked."))
    if verdict:
        raise HTTPException(422, tr("Dự đoán này đã đúng.", "This prediction is already correct."))
    actual = result["actual_output"]
    steps = result["trace"]["steps"]
    context = {
        "goal": i18n.pick(lv, "goal"), "code": result["code"], "prediction": V.normalize_output(prediction),
        "actual_output": actual, "expected_output": result["expected_output"],
        "passed": result["passed"], "trace": steps[:PREDICT_TRACE_STEPS],
        "trace_truncated": result["trace"]["truncated"] or len(steps) > PREDICT_TRACE_STEPS,
    }
    guess = V.normalize_output(prediction)
    fallback = tr(
        f"Bạn đoán:\n{guess}\nChương trình in:\n{actual or '(không in gì)'}\n"
        "Mở «Theo dõi từng bước» để xem mỗi dòng print chạy lúc nào.",
        f"You predicted:\n{guess}\nThe program prints:\n{actual or '(nothing)'}\n"
        "Open \"Step-by-step trace\" to see when each print line runs.")
    return tutor.feedback("predict", context, fallback, client=_client_ip(request))


@app.get("/api/rows/levels/{level_id}/hint")
def rows_hint(level_id: str, level: int = Query(..., ge=1, le=3),
              error_group: Optional[Literal[
                  "syntax", "bad_indent", "missing_colon", "wrong_order", "output_mismatch",
                  "missing_construct", "empty"]] = None):
    return hints.rows_hint(rows.get_level(level_id), level, error_group)


@app.post("/api/rows/levels/{level_id}/hint")
def rows_coach(level_id: str, req: RowsHintRequest, request: Request,
               level: int = Query(..., ge=1, le=3)):
    config = rows.get_level(level_id)
    diagnosis = rows.run_level(config, [row.model_dump() for row in req.rows],
                               include_trace=req.trace_step is not None)
    hint = hints.rows_hint(config, level, diagnosis["error_group"])
    if diagnosis["passed"] or not diagnosis["code"]:
        return hint
    context = {
        "goal": i18n.pick(config, "goal"),
        "hint_level": level,
        "tier": level,  # deprecated alias of hint_level, kept for existing n8n workflows
        "code": diagnosis["code"],
        "diagnosis": diagnosis["message"], "error_group": diagnosis["error_group"],
        "error_row": diagnosis["row"], "actual_output": diagnosis["actual_output"],
        "expected_output": diagnosis["expected_output"], "reference": hint["text"],
    }
    if req.trace_step is not None:
        steps = diagnosis["trace"]["steps"]
        if req.trace_step >= len(steps):
            raise HTTPException(422, tr("Bước chạy này không có trong chương trình.",
                                        "This step is not in the program."))
        context["current_step"] = {"step": req.trace_step + 1, **steps[req.trace_step]}
    return {"level": level, **tutor.feedback("coach", context, hint["text"], client=_client_ip(request))}


# --------------------------------------------------------------------------- static frontend

FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"


def build_id() -> str:
    """A short id that changes whenever the frontend code changes.

    ``SYNTAX_STACK_BUILD`` (e.g. the git commit) wins when set; otherwise it is a hash of the
    shipped HTML/CSS/JS, so a redeploy with changed files always produces a new id.
    """
    env = os.getenv("SYNTAX_STACK_BUILD", "").strip()
    if env:
        return re.sub(r"[^A-Za-z0-9._-]", "", env)[:12] or "dev"
    h = hashlib.sha1()
    for p in sorted(FRONTEND_DIR.rglob("*")):
        if p.is_file() and p.suffix in (".html", ".css", ".js") and "_screens" not in p.parts:
            h.update(p.relative_to(FRONTEND_DIR).as_posix().encode())
            h.update(p.read_bytes())
    return h.hexdigest()[:10]


def render_index(build: str) -> str:
    """index.html with every stylesheet and module URL stamped with ``?v=<build>``.

    The JS modules import each other by plain relative paths (``./game.js``), so an import map
    re-points each module URL at its versioned twin. A CDN therefore never pairs new HTML with
    old CSS/JS after a deploy: new code always has new URLs.
    """
    html = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")
    html = re.sub(r'((?:href|src)=")((?:css|js)/[^"?#]+\.(?:css|js))"', rf'\1\2?v={build}"', html)
    modules = sorted(p.relative_to(FRONTEND_DIR).as_posix() for p in (FRONTEND_DIR / "js").glob("*.js"))
    importmap = json.dumps({"imports": {f"/{m}": f"/{m}?v={build}" for m in modules}}, indent=1)
    tag = f'<script type="importmap">\n{importmap}\n</script>\n'
    return html.replace('<script type="module"', tag + '<script type="module"', 1)


def content_security_policy(html: str, ws_origin: str = "") -> str:
    """CSP for the page: own scripts plus the inline import map (allowed by its exact hash), Google
    Fonts, Cloudflare Web Analytics and Live2D's Cubism Core (one exact file), nothing else. The JSON-LD block is data, not script, so
    CSP does not apply to it. Cloudflare's inline bot-detection snippet stays blocked on purpose:
    it changes on every request, so it can only be allowed with 'unsafe-inline'.

    ``connect-src`` also names the site's own WebSocket origin (``wss://host``) explicitly: ``'self'`` covers
    ws:/wss: in current Chrome and Firefox but not in every Safari, and nothing but the own origin is opened."""
    hashes = [
        "'sha256-" + base64.b64encode(hashlib.sha256(body.encode()).digest()).decode() + "'"
        for body in re.findall(r'<script type="importmap">(.*?)</script>', html, re.S)
    ]
    return "; ".join([
        "default-src 'self'",
        # Cloudflare Web Analytics: the beacon script, which reports to cloudflareinsights.com
        # Live2D Cubism Core (Chat with Misaki): Live2D's official file, by its exact path
        "script-src 'self' https://static.cloudflareinsights.com " + " ".join(hashes)
        + " https://cubism.live2d.com/sdk-web/cubismcore/live2dcubismcore.min.js",
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",  # inline style="--c:..." on LEDs
        "font-src 'self' https://fonts.gstatic.com",
        "img-src 'self' data:",
        ("connect-src 'self' https://cloudflareinsights.com" + (f" {ws_origin}" if ws_origin else "")),
        "manifest-src 'self'",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "frame-ancestors 'none'",
    ])


if FRONTEND_DIR.is_dir():
    BUILD_ID = build_id()
    _INDEX_HTML = render_index(BUILD_ID)
    _INDEX_CSP = content_security_policy(_INDEX_HTML)
    _CSP_BY_ORIGIN: dict[str, str] = {}

    def _ws_origin(request: Request) -> str:
        """``wss://host`` (``ws://host`` over plain http) of the site as the visitor reaches it (same rules as the
        public URL of a duel link); empty when the host looks wrong."""
        base = rooms.public_base(headers=request.headers, scheme=request.url.scheme, netloc=request.url.netloc)
        scheme, _, host = base.partition("://")
        if scheme not in ("http", "https") or not host or "/" in host or not rooms._HOST_RE.match(host):
            return ""
        return ("wss://" if scheme == "https" else "ws://") + host

    @app.get("/", include_in_schema=False)
    @app.get("/index.html", include_in_schema=False)
    def _index(request: Request) -> HTMLResponse:
        origin = _ws_origin(request)
        csp = _INDEX_CSP
        if origin:
            csp = _CSP_BY_ORIGIN.get(origin)
            if csp is None:
                csp = content_security_policy(_INDEX_HTML, origin)
                if len(_CSP_BY_ORIGIN) < 32:  # bounded: a visitor can pick the Host header
                    _CSP_BY_ORIGIN[origin] = csp
        return HTMLResponse(_INDEX_HTML, headers={"Cache-Control": "no-cache", "X-Build": BUILD_ID,
                                                  "Content-Security-Policy": csp})

    # mounted last so it never shadows /api or the rendered index above
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
