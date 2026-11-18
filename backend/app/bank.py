"""Code Rescue puzzle bank access, selection and answer checking.

The bank (``data/puzzles.sqlite``) is produced offline by ``scripts/generate_bank.py``.
At play time nothing is generated: puzzles are only *selected* from the bank. Parsons answers are
run through the shared validator because the player's arrangement is free-form.
"""
from __future__ import annotations

import json
import os
import random
import sqlite3
from pathlib import Path
from typing import Optional

from . import validator as V

DB_PATH = Path(os.environ.get("SYNTAX_STACK_DB", Path(__file__).resolve().parents[1] / "data" / "puzzles.sqlite"))

TOPICS = ("variables", "conditions", "loops", "functions")
TYPES = ("parsons", "fill_blank", "predict_output", "find_bug")
LEVELS = ("beginner", "intermediate", "advanced")
MAX_INDENT = 2

# Selection weights per level (spec 4.2): advanced favours find_bug / predict_output.
TYPE_WEIGHTS = {
    "beginner": {"fill_blank": 3, "parsons": 3, "predict_output": 2, "find_bug": 1},
    "intermediate": {"fill_blank": 2, "parsons": 2, "predict_output": 2, "find_bug": 2},
    "advanced": {"fill_blank": 1, "parsons": 1, "predict_output": 3, "find_bug": 3},
}


class BankError(Exception):
    """Base for errors that map to HTTP statuses."""

    status = 400


class NotFound(BankError):
    status = 404


class Malformed(BankError):
    status = 422


# --------------------------------------------------------------------------- access


def _connect() -> sqlite3.Connection:
    if not DB_PATH.exists():
        raise NotFound(f"Chưa có ngân hàng câu đố ({DB_PATH.name}). Chạy scripts/generate_bank.py trước.")
    con = sqlite3.connect(f"{DB_PATH.as_uri()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def _row_to_dict(r: sqlite3.Row) -> dict:
    d = dict(r)
    d["hints"] = json.loads(d["hints"])
    d["data"] = json.loads(d["data"])
    return d


def count_puzzles() -> int:
    if not DB_PATH.exists():
        return 0
    con = _connect()
    try:
        return con.execute("SELECT COUNT(*) FROM puzzles WHERE debug_only = 0").fetchone()[0]
    finally:
        con.close()


def get_puzzle(puzzle_id: str) -> dict:
    con = _connect()
    try:
        r = con.execute("SELECT * FROM puzzles WHERE id = ?", (puzzle_id,)).fetchone()
    finally:
        con.close()
    if r is None:
        raise NotFound(f"Không tìm thấy câu đố '{puzzle_id}'.")
    return _row_to_dict(r)


# --------------------------------------------------------------------------- public view


def _view_options(options: list[dict], puzzle_id: str, level: str) -> list[dict]:
    """The options a level sees, in display order.

    The bank stores the correct option within the first three so the beginner view always contains
    it. Showing that stored order as-is would mean the 4th option is never correct, so the view is
    re-ordered with a shuffle seeded by (puzzle id, level): deterministic per request, and ids are
    unchanged so answer checking does not depend on display order.
    """
    limit = 3 if level == "beginner" else 4
    view = list(options[:limit])
    random.Random(f"{puzzle_id}:{level}").shuffle(view)
    return view


def _public_options(options: list[dict], puzzle_id: str, level: str) -> list[dict]:
    return [{"id": o["id"], "text": o["text"]} for o in _view_options(options, puzzle_id, level)]


def public_puzzle(row: dict, level: str = "intermediate") -> dict:
    """The player-facing puzzle. Never contains the answer."""
    typ, data = row["type"], row["data"]
    out = {
        "id": row["id"], "template_id": row["template_id"], "topic": row["topic"], "type": typ,
        "tier": row["tier"], "prompt": row["prompt"], "code": row["code"],
        "expected_output": None if typ == "predict_output" else row["expected_output"],
        "lines": None, "options": None,
    }
    if typ in ("fill_blank", "predict_output"):
        out["options"] = _public_options(data["options"], row["id"], level)
    elif typ == "parsons":
        out["lines"] = [{"id": l["id"], "text": l["text"]} for l in data["lines"]]
    elif typ == "find_bug":
        out["lines"] = [{"id": l["id"], "text": l["text"], "indent": l["indent"]} for l in data["lines"]]
        out["options"] = [{"id": o["id"], "line_id": o["line_id"], "text": o["text"]}
                          for o in _view_options(data["options"], row["id"], level)]
    return out


# --------------------------------------------------------------------------- selection


def select_puzzle(*, kind: str, topic: Optional[str], tier: Optional[int], level: str,
                  template_id: Optional[str], exclude_ids: list[str],
                  exclude_templates: list[str]) -> dict:
    excl_ids = set(exclude_ids or [])
    excl_tpl = set(exclude_templates or [])
    con = _connect()
    try:
        if kind == "debug":
            if not template_id:
                raise Malformed("kind 'debug' cần có template_id.")
            rows = con.execute("SELECT id, type, debug_only FROM puzzles WHERE template_id = ?",
                               (template_id,)).fetchall()
            if not rows:
                raise NotFound(f"Không tìm thấy mẫu câu đố '{template_id}'.")
            rows = [r for r in rows if r["id"] not in excl_ids]
            bug_rows = [r for r in rows if r["type"] == "find_bug"]
            pool = bug_rows or [r for r in rows if not r["debug_only"]]
            if not pool:
                raise NotFound("Không còn biến thể nào của mẫu này để dùng cho câu đố Debug.")
        else:
            if topic is None:
                topic = random.choice(TOPICS)
            if tier is None:
                tier = 3
            rows = con.execute(
                "SELECT id, template_id, type FROM puzzles WHERE topic = ? AND tier = ? AND debug_only = 0",
                (topic, tier)).fetchall()
            rows = [r for r in rows if r["id"] not in excl_ids]
            if template_id:
                rows = [r for r in rows if r["template_id"] == template_id]
            if not rows:
                raise NotFound("Không có câu đố nào khớp với bộ lọc.")
            preferred = [r for r in rows if r["template_id"] not in excl_tpl]
            pool = preferred or rows  # exclude_templates is only a soft preference
        if kind == "debug":
            chosen = random.choice(pool)
        else:
            weights = TYPE_WEIGHTS.get(level, TYPE_WEIGHTS["intermediate"])
            chosen = random.choices(pool, weights=[weights[r["type"]] for r in pool], k=1)[0]
        r = con.execute("SELECT * FROM puzzles WHERE id = ?", (chosen["id"],)).fetchone()
        return _row_to_dict(r)
    finally:
        con.close()


# --------------------------------------------------------------------------- answers


def _result(row: dict, correct: bool, reveal: bool, group: Optional[str], message: str,
            actual: Optional[str], note: Optional[str] = None) -> dict:
    show = correct or reveal
    explanation = None
    if show:
        explanation = row["explanation"] if correct or not note else f"{note} {row['explanation']}"
    return {
        "correct": correct,
        "error_group": None if correct else group,
        "message": message,
        "actual_output": actual,
        "solution_code": row["solution_code"] if show else None,
        "explanation": explanation,
    }


def _find_option(data: dict, option_id: Optional[str]) -> dict:
    if not option_id:
        raise Malformed("Thiếu option_id.")
    for o in data["options"]:
        if o["id"] == option_id:
            return o
    raise Malformed(f"option_id '{option_id}' không thuộc câu đố này.")


def check_answer(row: dict, *, option_id: Optional[str] = None, order: Optional[list[dict]] = None,
                 line_id: Optional[str] = None, reveal: bool = False, diagnose=None) -> dict:
    """``diagnose`` replaces ``validator.diagnose`` for parsons (custom puzzles pass the sandboxed one)."""
    typ, data = row["type"], row["data"]
    ok_msg = "Chính xác! Chương trình in đúng đầu ra."

    if typ == "fill_blank":
        opt = _find_option(data, option_id)
        if opt["correct"]:
            return _result(row, True, reveal, None, ok_msg, opt["actual_output"])
        return _result(row, False, reveal, opt["group"], opt["message"], opt["actual_output"], opt["note"])

    if typ == "predict_output":
        opt = _find_option(data, option_id)
        if opt["correct"]:
            return _result(row, True, reveal, None, "Chính xác!", row["expected_output"])
        msg = ("Chưa đúng. Chương trình thật sự in ra: " + V.describe_output(row["expected_output"]) + "."
               if reveal else "Chưa đúng, hãy theo dõi lại chương trình từng dòng.")
        return _result(row, False, reveal, "wrong_choice", msg,
                       row["expected_output"] if reveal else None, opt["note"])

    if typ == "find_bug":  # v2: the player picks one whole-line edit; any line_id sent is ignored
        opt = _find_option(data, option_id)
        if opt["correct"]:
            return _result(row, True, reveal, None, "Chính xác! Sau khi sửa, chương trình in đúng đầu ra.",
                           opt["actual_output"])
        if opt["line_id"] != data["bug_line"]:
            msg = "Dòng này không phải dòng bị lỗi nên chương trình vẫn chạy sai. " + (opt["message"] or "")
            return _result(row, False, reveal, "wrong_line", msg.strip(), opt["actual_output"], opt["note"])
        return _result(row, False, reveal, "wrong_fix", opt["message"], opt["actual_output"], opt["note"])

    if typ == "parsons":
        return _check_parsons(row, order, reveal, diagnose or V.diagnose)

    raise Malformed("Loại câu đố không được hỗ trợ.")  # pragma: no cover


def _check_parsons(row: dict, order: Optional[list[dict]], reveal: bool, diagnose) -> dict:
    data = row["data"]
    if not order:
        raise Malformed("Thiếu 'order'.")
    texts = {l["id"]: l["text"] for l in data["lines"]}
    ids = [o["line_id"] for o in order]
    if sorted(ids) != sorted(texts):
        raise Malformed("'order' phải chứa mỗi dòng đúng một lần.")
    for o in order:
        if not (0 <= o["indent"] <= MAX_INDENT):
            raise Malformed(f"indent phải từ 0 đến {MAX_INDENT}.")
    code = "\n".join("    " * o["indent"] + texts[o["line_id"]] for o in order)
    diag = diagnose(code, row["expected_output"])
    if diag.passed:
        return _result(row, True, reveal, None, "Chính xác! Chương trình in đúng đầu ra.", diag.actual_output)

    group = diag.error_group
    if diag.run is not None and diag.run.ok:  # ran, but printed something else: say why structurally
        sol = data["solution"]
        if ids != [s["line_id"] for s in sol]:
            group = "wrong_order"
        elif [o["indent"] for o in order] != [s["indent"] for s in sol]:
            group = "bad_indent"
    note = None
    for d in data.get("distractors", []):
        if d["code"] == code:
            note = d.get("note")
            break
    return _result(row, False, reveal, group, diag.message, diag.actual_output, note)
