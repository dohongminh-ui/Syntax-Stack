"""Custom puzzle sets: "paste your own code, get verified puzzles".

The learner's program is validated here (text only), then everything that executes it happens in the
sandbox child process (``sandbox.py``). Generated sets are kept in their own SQLite file
(``data/custom.sqlite``, created on demand, never committed) for 30 days. Puzzle ids look like
``c-<setid>-<n>``; ``main.py`` routes those ids here instead of to the bank.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import secrets
import sqlite3
import tempfile
import threading
import time
from contextlib import closing
from pathlib import Path
from typing import Optional

from . import bank, custom_gen, i18n, sandbox
from .i18n import tr

DB_PATH = Path(os.environ.get("SYNTAX_STACK_CUSTOM_DB",
                              Path(__file__).resolve().parents[1] / "data" / "custom.sqlite"))
TTL_S = 30 * 24 * 3600
RATE_LIMIT = 10             # new sets per client per window
RATE_WINDOW_S = 3600
MAX_TRACKED_CLIENTS = 20_000

_PUZZLE_ID = re.compile(r"^c-([a-z2-7]{8})-(\d{1,2})$")
_SET_ID = re.compile(r"^[a-z2-7]{8}$")


class CustomError(bank.BankError):
    """An error with an explicit HTTP status; the message (Vietnamese or English, by the request) is shown to the
    learner."""

    def __init__(self, message: str, status: int):
        super().__init__(message)
        self.status = status


def _now() -> float:
    return time.time()


def is_custom_id(puzzle_id: str) -> bool:
    return puzzle_id.startswith("c-")


# --------------------------------------------------------------------------- rate limit

_rate_lock = threading.Lock()
_hits: dict[str, list[float]] = {}


def client_key(client: Optional[str]) -> str:
    return hashlib.sha256(("syntax-stack-custom:" + (client or "unknown")).encode()).hexdigest()[:16]


def reset_rate_limits() -> None:
    with _rate_lock:
        _hits.clear()


def _take_slot(key: str) -> None:
    """Record one creation for ``key`` or raise 429 when it already made ``RATE_LIMIT`` in the window."""
    now = _now()
    with _rate_lock:
        if len(_hits) > MAX_TRACKED_CLIENTS:
            for k in [k for k, v in _hits.items() if not v or v[-1] < now - RATE_WINDOW_S]:
                del _hits[k]
        recent = [t for t in _hits.get(key, []) if t > now - RATE_WINDOW_S]
        if len(recent) >= RATE_LIMIT:
            _hits[key] = recent
            raise CustomError(
                tr(f"Bạn đã tạo {RATE_LIMIT} bộ câu đố trong một giờ qua, đó là mức tối đa. Hãy thử lại sau.",
                   f"You made {RATE_LIMIT} puzzle sets in the last hour, which is the maximum. Please try again later."),
                429)
        recent.append(now)
        _hits[key] = recent


# --------------------------------------------------------------------------- storage

_db_path_cache: Optional[Path] = None
_db_lock = threading.Lock()


def _db_path() -> Path:
    """DB_PATH, or a file in the temp directory when the data directory is not writable (read-only image)."""
    global _db_path_cache
    path = DB_PATH
    if path.exists():
        return path
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if os.access(path.parent, os.W_OK):
            return path
    except OSError:
        pass
    with _db_lock:
        if _db_path_cache is None:
            _db_path_cache = Path(tempfile.gettempdir()) / "syntax-stack-custom.sqlite"
        return _db_path_cache


def _connect() -> sqlite3.Connection:
    con = sqlite3.connect(_db_path(), timeout=5)
    con.row_factory = sqlite3.Row
    con.execute("""CREATE TABLE IF NOT EXISTS custom_sets (
        id TEXT PRIMARY KEY,
        created_at REAL NOT NULL,
        source_code TEXT NOT NULL,
        client_hash TEXT NOT NULL,
        meta TEXT NOT NULL,
        puzzles TEXT NOT NULL)""")
    con.execute("CREATE INDEX IF NOT EXISTS idx_custom_sets_created ON custom_sets (created_at)")
    return con


def purge_expired() -> int:
    """Delete sets older than 30 days; returns how many were removed."""
    with closing(_connect()) as con:
        cur = con.execute("DELETE FROM custom_sets WHERE created_at < ?", (_now() - TTL_S,))
        con.commit()
        return cur.rowcount


def _new_set_id() -> str:
    return base64.b32encode(secrets.token_bytes(5)).decode("ascii").lower()  # 5 bytes -> 8 chars, no padding


def _load_set(set_id: str) -> dict:
    if not _SET_ID.match(set_id):
        raise CustomError(tr("Không tìm thấy bộ câu đố này.", "This puzzle set was not found."), 404)
    with closing(_connect()) as con:
        r = con.execute("SELECT * FROM custom_sets WHERE id = ?", (set_id,)).fetchone()
    if r is None or r["created_at"] < _now() - TTL_S:
        raise CustomError(tr("Không tìm thấy bộ câu đố này, có thể nó đã hết hạn (30 ngày).",
                             "This puzzle set was not found, it may have expired (30 days)."), 404)
    return {"id": r["id"], "meta": json.loads(r["meta"]), "puzzles": json.loads(r["puzzles"])}


# --------------------------------------------------------------------------- public API


def _view(set_id: str, meta: dict, puzzles: list[dict], level: str, *, with_source: bool) -> dict:
    # The source program and its output answer every puzzle in the set (the fix, the blank, the order,
    # the predicted output), so only the creator's POST response carries them. A shared GET does not.
    return {
        "id": set_id, "topic": meta["topic"],
        "code": meta["code"] if with_source else None,
        "expected_output": meta["expected_output"] if with_source else None,
        "puzzles": [bank.public_puzzle(p, level) for p in puzzles],
        "skipped": [{"type": sk["type"], "reason": i18n.pick(sk, "reason")} for sk in meta["skipped"]],
    }


def create_set(code: str, level: str, client: Optional[str]) -> dict:
    try:
        clean, tree = custom_gen.prepare_source(code)
    except custom_gen.InvalidSource as e:
        raise CustomError(tr(str(e), e.en), 422) from None
    key = client_key(client)
    _take_slot(key)
    try:
        out = sandbox.generate(clean)
    except sandbox.SandboxError:
        raise CustomError(tr("Chương trình chạy quá lâu hoặc dùng quá nhiều tài nguyên nên đã bị dừng.",
                             "The program ran for too long or used too many resources, so it was stopped."),
                          422) from None
    if not out.get("ok"):
        raise CustomError(str(i18n.pick_get(out, "message")
                              or tr("Chương trình không chạy được.", "The program could not run.")), 422)
    generated = out["puzzles"]
    if not generated:
        reasons = " ".join(i18n.pick(s, "reason") for s in out["skipped"])
        raise CustomError(tr("Không tạo được câu đố nào từ đoạn mã này. ",
                             "No puzzle could be made from this code. ") + reasons, 422)

    set_id = _new_set_id()
    topic = custom_gen.infer_topic(tree)
    puzzles = []
    for n, p in enumerate(generated, 1):
        puzzles.append({**p, "id": f"c-{set_id}-{n}", "template_id": "custom", "topic": topic, "tier": 1})
    meta = {"topic": topic, "code": out["code"], "expected_output": out["expected_output"],
            "skipped": out["skipped"]}
    with closing(_connect()) as con:
        con.execute("DELETE FROM custom_sets WHERE created_at < ?", (_now() - TTL_S,))  # lazy purge
        con.execute("INSERT INTO custom_sets VALUES (?,?,?,?,?,?)",
                    (set_id, _now(), out["code"], key, json.dumps(meta, ensure_ascii=False),
                     json.dumps(puzzles, ensure_ascii=False)))
        con.commit()
    return _view(set_id, meta, puzzles, level, with_source=True)


def get_set(set_id: str, level: str) -> dict:
    s = _load_set(set_id)
    return _view(s["id"], s["meta"], s["puzzles"], level, with_source=False)


def get_puzzle(puzzle_id: str) -> dict:
    """The stored puzzle row (with answers). Same shape as ``bank.get_puzzle``."""
    m = _PUZZLE_ID.match(puzzle_id)
    if not m:
        raise CustomError(tr(f"Không tìm thấy câu đố '{puzzle_id}'.", f"Puzzle '{puzzle_id}' was not found."), 404)
    for p in _load_set(m.group(1))["puzzles"]:
        if p["id"] == puzzle_id:
            return p
    raise CustomError(tr(f"Không tìm thấy câu đố '{puzzle_id}'.", f"Puzzle '{puzzle_id}' was not found."), 404)


def diagnose(code: str, expected: str):
    """Sandboxed ``validator.diagnose`` for answer checks of custom puzzles."""
    return sandbox.diagnose(code, expected)
