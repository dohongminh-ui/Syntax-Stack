"""Syntax Stack backend: FastAPI app. API under /api, static frontend at / (if ../frontend exists)."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Literal, Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import bank, hints, rows, tutor
from . import validator as V

if sys.version_info < (3, 12):  # the validator reads ast node.type_params (3.12+)
    raise RuntimeError(
        f"Syntax Stack needs Python 3.12 or newer; this is {sys.version.split()[0]}.")

# The interactive API docs (/docs, /redoc, /openapi.json) are a free map of the API, so they are off
# unless SYNTAX_STACK_API_DOCS=1 (handy locally).
_DOCS = os.getenv("SYNTAX_STACK_API_DOCS", "").strip() in ("1", "true", "yes")
app = FastAPI(title="Syntax Stack API", version="1.0",
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


class _BodyLimit:
    """Pure ASGI middleware: 413 for a declared Content-Length over the limit; a body streamed
    without one is cut off at the limit (FastAPI then answers 400)."""

    def __init__(self, app, limit: int):
        self.app, self.limit = app, limit

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] in ("GET", "HEAD", "OPTIONS"):
            return await self.app(scope, receive, send)
        declared = dict(scope.get("headers") or []).get(b"content-length", b"")
        if declared.isdigit() and int(declared) > self.limit:
            response = JSONResponse({"detail": "Yêu cầu quá lớn."}, status_code=413)
            return await response(scope, receive, send)
        seen = 0

        async def limited():
            nonlocal seen
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body", b""))
                if seen > self.limit:
                    raise ValueError("request body over the size limit")
            return message

        return await self.app(scope, limited, send)


app.add_middleware(_BodyLimit, limit=MAX_BODY_BYTES)  # added last = runs first


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


class OrderItem(BaseModel):
    line_id: str = Field(max_length=40)
    indent: int


class AnswerRequest(BaseModel):
    option_id: Optional[str] = Field(default=None, max_length=40)
    order: Optional[list[OrderItem]] = Field(default=None, max_length=30)
    line_id: Optional[str] = Field(default=None, max_length=40)
    reveal: bool = False


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


# Vietnamese topic names, as the frontend shows them (frontend/js/pieces.js: TOPIC_NAMES).
TOPIC_NAMES_VI = {"variables": "Biến", "conditions": "Điều kiện", "loops": "Vòng lặp", "functions": "Hàm"}
PREDICT_TRACE_STEPS = 40


# --------------------------------------------------------------------------- Code Rescue


@app.get("/api/health")
def health():
    return {"ok": True, "puzzles": bank.count_puzzles(), "tutor": tutor.stats()}


@app.post("/api/puzzle/next")
def puzzle_next(req: NextRequest):
    if req.kind == "debug":
        if not req.template_id:
            raise HTTPException(422, "kind 'debug' cần có template_id.")
    elif req.kind == "rescue" and (req.topic is None or req.tier is None):
        raise HTTPException(422, "kind 'rescue' cần có topic và tier.")
    row = bank.select_puzzle(
        kind=req.kind, topic=req.topic, tier=req.tier, level=req.level, template_id=req.template_id,
        exclude_ids=req.exclude_ids, exclude_templates=req.exclude_templates)
    return bank.public_puzzle(row, req.level)


@app.post("/api/puzzle/{puzzle_id}/answer")
def puzzle_answer(puzzle_id: str, req: AnswerRequest):
    row = bank.get_puzzle(puzzle_id)
    return bank.check_answer(
        row, option_id=req.option_id,
        order=[o.model_dump() for o in req.order] if req.order is not None else None,
        line_id=req.line_id, reveal=req.reveal)


@app.get("/api/puzzle/{puzzle_id}/hint")
def puzzle_hint(puzzle_id: str, level: int = Query(..., ge=1, le=3)):
    return hints.puzzle_hint(bank.get_puzzle(puzzle_id), level)


@app.post("/api/puzzle/{puzzle_id}/explain")
def puzzle_explain(puzzle_id: str, req: AnswerRequest, request: Request):
    puzzle = bank.get_puzzle(puzzle_id)
    order = [item.model_dump() for item in req.order] if req.order is not None else None
    result = bank.check_answer(puzzle, option_id=req.option_id, order=order, reveal=True)
    if result["correct"]:
        raise HTTPException(422, "Câu trả lời này đã đúng.")
    data = puzzle["data"]
    code = puzzle["code"]
    if puzzle["type"] == "parsons":
        lines = {line["id"]: line["text"] for line in data["lines"]}
        choice = "\n".join("    " * item["indent"] + lines[item["line_id"]] for item in order)
    else:
        option = next(item for item in data["options"] if item["id"] == req.option_id)
        choice = option["text"]
        if puzzle["type"] == "find_bug":
            line_number = next(i for i, line in enumerate(data["lines"], 1)
                               if line["id"] == option["line_id"])
            choice = f"Dòng {line_number}: {choice}"
            code = "\n".join("    " * line["indent"] + line["text"] for line in data["lines"])
    return tutor.feedback("explain", {
        "prompt": puzzle["prompt"], "type": puzzle["type"], "code": code,
        "choice": choice, "diagnosis": result["message"], "actual_output": result["actual_output"],
        "expected_output": puzzle["expected_output"], "reference": result["explanation"],
        "solution": result["solution_code"],
    }, result["explanation"] or result["message"], client=_client_ip(request))


@app.get("/api/puzzle/{puzzle_id}/rematch")
def puzzle_rematch(puzzle_id: str, request: Request, level: Level = "intermediate"):
    original = bank.get_puzzle(puzzle_id)
    followup = bank.select_puzzle(
        kind="rescue", topic=original["topic"], tier=original["tier"], level=level,
        template_id=original["template_id"], exclude_ids=[original["id"]], exclude_templates=[],
    )
    intro = tutor.feedback("rematch", {
        "previous_prompt": original["prompt"], "next_prompt": followup["prompt"],
        "topic": original["topic"], "hint": followup["hints"][0],
    }, "Thử áp dụng lại quy tắc vừa gặp vào câu đố mới này.", client=_client_ip(request))
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
                         "template_id": puzzle["template_id"], "prompt": puzzle["prompt"],
                         "diagnosis": diagnosis})
    if not mistakes:
        raise HTTPException(422, "Không có lỗi nào để tổng kết.")
    topic_counts: dict[str, int] = {}
    for m in mistakes:
        topic_counts[m["topic"]] = topic_counts.get(m["topic"], 0) + 1
    focus_topic = max(topic_counts, key=topic_counts.get)  # ties: first in order of appearance
    name = TOPIC_NAMES_VI.get(focus_topic, focus_topic)
    fallback = (f"Ván này bạn sai nhiều nhất ở chủ đề {name} ({topic_counts[focus_topic]} lần). "
                "Hãy chơi Luyện tập chủ đề này để quen lại quy tắc trước ván sau.")
    if req.end_reason == "crash":
        fallback += " Nhớ rằng hai câu trả lời sai sẽ kết thúc một ván Code Rescue."
    context = {"level": req.level, "mode": req.mode, "end_reason": req.end_reason,
               "topic_counts": topic_counts, "focus_topic": focus_topic, "mistakes": mistakes}
    reply = tutor.feedback("debrief", context, fallback, client=_client_ip(request))
    return {**reply, "focus_topic": focus_topic}


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
        raise HTTPException(422, "Hãy viết lời giải thích của bạn.")
    result = rows.run_level(lv, [r.model_dump() for r in req.rows])
    if not result["passed"]:
        raise HTTPException(422, "Hãy hoàn thành màn trước khi giải thích.")
    return tutor.feedback("teach_back", {
        "goal": lv["goal"], "code": result["code"], "output": result["actual_output"],
        "learner_explanation": reflection,
    }, "Nếu đổi đúng một mảnh mã, đầu ra sẽ thay đổi thế nào? / What would change in the output if you swapped one tile?",
        client=_client_ip(request))


@app.post("/api/rows/levels/{level_id}/explain-prediction")
def rows_explain_prediction(level_id: str, req: RunRequest, request: Request):
    """Explain a wrong output prediction. The server re-runs the board; the client sends its guess."""
    lv = rows.get_level(level_id)
    prediction = (req.prediction or "").strip()
    if not prediction:
        raise HTTPException(422, "Hãy nhập dự đoán của bạn.")
    result = rows.run_level(lv, [r.model_dump() for r in req.rows], include_trace=True,
                            prediction=prediction)
    verdict = result["prediction"]["correct"]
    if verdict is None or result["actual_output"] is None:
        raise HTTPException(422, "Chương trình chưa chạy xong để đối chiếu dự đoán.")
    if verdict:
        raise HTTPException(422, "Dự đoán này đã đúng.")
    actual = result["actual_output"]
    steps = result["trace"]["steps"]
    context = {
        "goal": lv["goal"], "code": result["code"], "prediction": V.normalize_output(prediction),
        "actual_output": actual, "expected_output": result["expected_output"],
        "passed": result["passed"], "trace": steps[:PREDICT_TRACE_STEPS],
        "trace_truncated": result["trace"]["truncated"] or len(steps) > PREDICT_TRACE_STEPS,
    }
    guess = V.normalize_output(prediction)
    shown = actual or "(không in gì)"
    fallback = (f"Bạn đoán:\n{guess}\nChương trình in:\n{shown}\n"
                "Mở «Theo dõi từng bước» để xem mỗi dòng print chạy lúc nào.")
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
        "goal": config["goal"],
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
            raise HTTPException(422, "Bước chạy này không có trong chương trình.")
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


def content_security_policy(html: str) -> str:
    """CSP for the page: own scripts plus the inline import map (allowed by its exact hash), Google
    Fonts and Cloudflare Web Analytics, nothing else. The JSON-LD block is data, not script, so
    CSP does not apply to it. Cloudflare's inline bot-detection snippet stays blocked on purpose:
    it changes on every request, so it can only be allowed with 'unsafe-inline'."""
    hashes = [
        "'sha256-" + base64.b64encode(hashlib.sha256(body.encode()).digest()).decode() + "'"
        for body in re.findall(r'<script type="importmap">(.*?)</script>', html, re.S)
    ]
    return "; ".join([
        "default-src 'self'",
        # Cloudflare Web Analytics: the beacon script, which reports to cloudflareinsights.com
        "script-src 'self' https://static.cloudflareinsights.com " + " ".join(hashes),
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",  # inline style="--c:..." on LEDs
        "font-src 'self' https://fonts.gstatic.com",
        "img-src 'self' data:",
        "connect-src 'self' https://cloudflareinsights.com",
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

    @app.get("/", include_in_schema=False)
    @app.get("/index.html", include_in_schema=False)
    def _index() -> HTMLResponse:
        return HTMLResponse(_INDEX_HTML, headers={"Cache-Control": "no-cache", "X-Build": BUILD_ID,
                                                  "Content-Security-Policy": _INDEX_CSP})

    # mounted last so it never shadows /api or the rendered index above
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
