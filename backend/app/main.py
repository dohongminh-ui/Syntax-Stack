"""Syntax Stack backend: FastAPI app. API under /api, static frontend at / (if ../frontend exists)."""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Literal, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import bank, hints, rows, tutor

if sys.version_info < (3, 12):  # the validator reads ast node.type_params (3.12+)
    raise RuntimeError(
        f"Syntax Stack needs Python 3.12 or newer; this is {sys.version.split()[0]}.")

app = FastAPI(title="Syntax Stack API", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^http://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_methods=["*"],
    allow_headers=["*"],
)


# Cache policy for responses that pass through a CDN (Cloudflare caches .css/.js by default and
# otherwise falls back to its own 4-hour TTL). The frontend's files have fixed names and the JS
# modules import each other by plain relative paths, so a long cache would serve old CSS next to
# new JS after a deploy. Code and pages therefore revalidate every time (cheap: StaticFiles answers
# a matching ETag with 304); images and icons change rarely and may be cached for a day.
_REVALIDATE = (".html", ".css", ".js", ".json", ".xml", ".txt")
_CACHE_A_DAY = (".png", ".ico", ".svg")


@app.middleware("http")
async def _cache_headers(request, call_next):
    response = await call_next(request)
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
    template_id: Optional[str] = None
    exclude_ids: list[str] = Field(default_factory=list)
    exclude_templates: list[str] = Field(default_factory=list)


class OrderItem(BaseModel):
    line_id: str
    indent: int


class AnswerRequest(BaseModel):
    option_id: Optional[str] = None
    order: Optional[list[OrderItem]] = None
    line_id: Optional[str] = None
    reveal: bool = False


class TokenPlacement(BaseModel):
    id: str
    col: int


class RowPlacement(BaseModel):
    row: int
    tokens: list[TokenPlacement] = Field(default_factory=list)


class RunRequest(BaseModel):
    rows: list[RowPlacement] = Field(default_factory=list)
    trace: bool = False
    prediction: Optional[str] = Field(default=None, max_length=240)


class RowsHintRequest(RunRequest):
    trace_step: Optional[int] = Field(default=None, ge=0)


class RowsTwistRequest(RunRequest):
    baseline: list[RowPlacement]


class TeachBackRequest(RunRequest):
    reflection: str = Field(min_length=1, max_length=400)


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
def puzzle_explain(puzzle_id: str, req: AnswerRequest):
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
    }, result["explanation"] or result["message"])


@app.get("/api/puzzle/{puzzle_id}/rematch")
def puzzle_rematch(puzzle_id: str, level: Level = "intermediate"):
    original = bank.get_puzzle(puzzle_id)
    followup = bank.select_puzzle(
        kind="rescue", topic=original["topic"], tier=original["tier"], level=level,
        template_id=original["template_id"], exclude_ids=[original["id"]], exclude_templates=[],
    )
    intro = tutor.feedback("rematch", {
        "previous_prompt": original["prompt"], "next_prompt": followup["prompt"],
        "topic": original["topic"], "hint": followup["hints"][0],
    }, "Thử áp dụng lại quy tắc vừa gặp vào câu đố mới này.")
    return {**intro, "puzzle": bank.public_puzzle(followup, level)}


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
def rows_teach_back(level_id: str, req: TeachBackRequest):
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
    }, "Nếu đổi đúng một mảnh mã, đầu ra sẽ thay đổi thế nào? / What would change in the output if you swapped one tile?")


@app.get("/api/rows/levels/{level_id}/hint")
def rows_hint(level_id: str, level: int = Query(..., ge=1, le=3),
              error_group: Optional[Literal[
                  "syntax", "bad_indent", "missing_colon", "wrong_order", "output_mismatch",
                  "missing_construct", "empty"]] = None):
    return hints.rows_hint(rows.get_level(level_id), level, error_group)


@app.post("/api/rows/levels/{level_id}/hint")
def rows_coach(level_id: str, req: RowsHintRequest, level: int = Query(..., ge=1, le=3)):
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
    return {"level": level, **tutor.feedback("coach", context, hint["text"])}


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


if FRONTEND_DIR.is_dir():
    BUILD_ID = build_id()
    _INDEX_HTML = render_index(BUILD_ID)

    @app.get("/", include_in_schema=False)
    @app.get("/index.html", include_in_schema=False)
    def _index() -> HTMLResponse:
        return HTMLResponse(_INDEX_HTML, headers={"Cache-Control": "no-cache", "X-Build": BUILD_ID})

    # mounted last so it never shadows /api or the rendered index above
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
