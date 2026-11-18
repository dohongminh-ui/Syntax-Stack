"""Ranked Code Rescue runs, the leaderboard and races. Contract: docs/ranked-and-race.md.

Trust model: the server never accepts a score. A run gets a server-chosen seed; the pieces are dealt from it
(``rescue_engine``), every puzzle is picked by the server (deterministically from the seed) and recorded, as
are the hints opened and the checked answers. At the end the browser sends only its list of moves and the
server replays the whole game, so the score is computed here. A move list that is not a legal game, or that
uses puzzles the server did not serve for that exact situation, is stored as ``rejected`` and never ranked.

Only a nickname and the SHA-256 of a random device id are stored, in ``ranked.sqlite`` next to the other
SQLite files on the Docker volume.
"""
from __future__ import annotations

import hmac
import os
import random
import re
import secrets
import sqlite3
import tempfile
import threading
import time
import unicodedata
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from . import bank, custom, nicknames, rescue_engine, rooms

DB_PATH = Path(os.environ.get("SYNTAX_STACK_RANKED_DB", custom.DB_PATH.parent / "ranked.sqlite"))

LEVELS = rescue_engine.LEVELS
PERIODS = ("day", "week", "all")
RUN_RATE_LIMIT = 30          # new runs per client IP per window
RACE_RATE_LIMIT = 10         # new races per client IP per window
PVP_RATE_LIMIT = 60          # quick-match / private duel / bot match requests per client IP per window
RATE_WINDOW_S = 3600
MAX_TRACKED_CLIENTS = 20_000
RUN_TTL_S = 3 * 3600         # a run must be finished within 3 hours of its start
KEEP_FINISHED_S = 90 * 24 * 3600
PVP_RATING_KEEP_S = 365 * 24 * 3600   # a device's PvP rating is forgotten after a year without a match
PVP_START_RATING = 1000
PVP_ELO_K = 32
MISAKI_LEVELS = 4                     # the Misaki ladder (docs/pvp.md section 5.2)
MISAKI_KEEP_S = 365 * 24 * 3600       # a device's ladder progress is forgotten after a year without a match
RACE_TTL_S = 7 * 24 * 3600
MAX_RACE_RUNS = 30
LEADERBOARD_SIZE = 50
MAX_SERVED_PER_RUN = 2000    # puzzles recorded per run (a legal game needs far fewer)
HISTORY_IDS = 500            # same window the browser sends as exclude_ids
HISTORY_TEMPLATES = 3        # same window as the browser's recentTemplates
VN_TZ = timezone(timedelta(hours=7))  # Asia/Ho_Chi_Minh, no daylight saving

_DEVICE_RE = re.compile(r"^[0-9a-f]{32}$")
_RUN_RE = re.compile(r"^[0-9a-f]{16}$")


class RankedError(bank.BankError):
    """An error with an explicit HTTP status; the message is Vietnamese and shown to the user."""

    def __init__(self, message: str, status: int):
        super().__init__(message)
        self.status = status


def _now() -> float:
    return time.time()


# --------------------------------------------------------------------------- rate limit


class _Limiter:
    def __init__(self, limit: int, message: str, window_s: int = RATE_WINDOW_S):
        self.limit, self.message, self.window_s = limit, message, window_s
        self._lock = threading.Lock()
        self._hits: dict[str, list[float]] = {}

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()

    def take(self, client: Optional[str]) -> None:
        key = rooms.client_key(client)
        now = _now()
        with self._lock:
            if len(self._hits) > MAX_TRACKED_CLIENTS:
                for k in [k for k, v in self._hits.items() if not v or v[-1] < now - self.window_s]:
                    del self._hits[k]
            recent = [t for t in self._hits.get(key, []) if t > now - self.window_s]
            if len(recent) >= self.limit:
                self._hits[key] = recent
                raise RankedError(self.message, 429)
            recent.append(now)
            self._hits[key] = recent


_run_limiter = _Limiter(RUN_RATE_LIMIT, f"Bạn đã bắt đầu {RUN_RATE_LIMIT} ván xếp hạng trong một giờ qua, "
                                        "đó là mức tối đa. Hãy thử lại sau.")
_race_limiter = _Limiter(RACE_RATE_LIMIT, f"Bạn đã tạo {RACE_RATE_LIMIT} cuộc đua trong một giờ qua, "
                                          "đó là mức tối đa. Hãy thử lại sau.")


_nickname_limiter = _Limiter(60, "Bạn đã xin quá nhiều tên trong một phút. Hãy thử lại sau.", 60)
_pvp_limiter = _Limiter(PVP_RATE_LIMIT, f"Bạn đã tìm trận đối kháng {PVP_RATE_LIMIT} lần trong một giờ qua, "
                                        "đó là mức tối đa. Hãy thử lại sau.")


def take_nickname_slot(client: Optional[str]) -> None:
    _nickname_limiter.take(client)


def take_pvp_slot(client: Optional[str]) -> None:
    _pvp_limiter.take(client)


def reset_rate_limits() -> None:
    _pvp_limiter.reset()
    _nickname_limiter.reset()
    _run_limiter.reset()
    _race_limiter.reset()


# --------------------------------------------------------------------------- storage

_db_lock = threading.Lock()          # also serialises writes (single process)
_db_path_cache: Optional[Path] = None
_ready: set[str] = set()


def _db_path() -> Path:
    """DB_PATH, or a file in the temp directory when its folder is not writable (read-only image)."""
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
            _db_path_cache = Path(tempfile.gettempdir()) / "syntax-stack-ranked.sqlite"
        return _db_path_cache


_SCHEMA = """
CREATE TABLE IF NOT EXISTS races (
    code TEXT PRIMARY KEY, seed INTEGER NOT NULL, level TEXT NOT NULL, created_by TEXT NOT NULL,
    created_at REAL NOT NULL, expires_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY, token_hash TEXT NOT NULL, kind TEXT NOT NULL, race TEXT, level TEXT NOT NULL,
    seed INTEGER NOT NULL, nickname TEXT NOT NULL, device_hash TEXT NOT NULL, created_at REAL NOT NULL,
    finished_at REAL, status TEXT NOT NULL DEFAULT 'open', reason TEXT,
    score INTEGER NOT NULL DEFAULT 0, locks INTEGER NOT NULL DEFAULT 0, mistakes INTEGER NOT NULL DEFAULT 0,
    bugs_fixed INTEGER NOT NULL DEFAULT 0, best_streak INTEGER NOT NULL DEFAULT 0,
    duration_s REAL, client_score INTEGER);
CREATE INDEX IF NOT EXISTS idx_runs_board ON runs (kind, level, status, finished_at);
CREATE INDEX IF NOT EXISTS idx_runs_race ON runs (race);
CREATE INDEX IF NOT EXISTS idx_runs_open ON runs (status, created_at);
CREATE TABLE IF NOT EXISTS served (
    run_id TEXT NOT NULL, seq INTEGER NOT NULL, puzzle_id TEXT NOT NULL, kind TEXT NOT NULL,
    req_topic TEXT, req_tier INTEGER, req_template TEXT, topic TEXT NOT NULL, template_id TEXT NOT NULL,
    hint INTEGER NOT NULL DEFAULT 0, correct INTEGER, PRIMARY KEY (run_id, seq));
CREATE INDEX IF NOT EXISTS idx_served_puzzle ON served (run_id, puzzle_id);
CREATE TABLE IF NOT EXISTS pvp_ratings (
    device_hash TEXT PRIMARY KEY, rating INTEGER NOT NULL, games INTEGER NOT NULL DEFAULT 0,
    wins INTEGER NOT NULL DEFAULT 0, losses INTEGER NOT NULL DEFAULT 0, updated_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS misaki_progress (
    device_hash TEXT NOT NULL, level INTEGER NOT NULL, games INTEGER NOT NULL DEFAULT 0,
    wins INTEGER NOT NULL DEFAULT 0, updated_at REAL NOT NULL, PRIMARY KEY (device_hash, level));
"""


def _connect() -> sqlite3.Connection:
    path = _db_path()
    con = sqlite3.connect(path, timeout=5)
    con.row_factory = sqlite3.Row
    key = str(path)
    if key not in _ready:
        with _db_lock:
            con.execute("PRAGMA journal_mode=WAL")
            con.executescript(_SCHEMA)
            _ready.add(key)
    return con


def _purge(con: sqlite3.Connection) -> None:
    """Lazy clean-up on writes: abandoned runs, old finished runs, expired races with their runs."""
    now = _now()
    con.execute("DELETE FROM runs WHERE status = 'open' AND created_at < ?", (now - RUN_TTL_S,))
    con.execute("DELETE FROM runs WHERE status != 'open' AND finished_at < ?", (now - KEEP_FINISHED_S,))
    con.execute("DELETE FROM runs WHERE race IN (SELECT code FROM races WHERE expires_at < ?)", (now,))
    con.execute("DELETE FROM races WHERE expires_at < ?", (now,))
    con.execute("DELETE FROM served WHERE run_id NOT IN (SELECT id FROM runs)")
    con.execute("DELETE FROM pvp_ratings WHERE updated_at < ?", (now - PVP_RATING_KEEP_S,))
    con.execute("DELETE FROM misaki_progress WHERE updated_at < ?", (now - MISAKI_KEEP_S,))


def _device_hash(device_id: str) -> str:
    return rooms._hash(device_id)


def _clean_identity(nickname: str, device_id: str) -> tuple[str, str]:
    nickname = rooms._clean_text(nickname, rooms.MAX_NICKNAME, "Biệt danh", required=True)
    if not nicknames.is_generated(nickname):
        raise RankedError("Hãy dùng tên được tạo ngẫu nhiên.", 422)
    nickname = unicodedata.normalize("NFC", nickname)
    if not isinstance(device_id, str) or not _DEVICE_RE.match(device_id):
        raise RankedError("Mã thiết bị không hợp lệ.", 422)
    return nickname, _device_hash(device_id)


# --------------------------------------------------------------------------- races (create / read)


def _load_race(con: sqlite3.Connection, code: str) -> sqlite3.Row:
    code = rooms._normalize_code(code)
    row = (con.execute("SELECT * FROM races WHERE code = ?", (code,)).fetchone()
           if rooms._CODE_RE.match(code) else None)
    if row is None:
        raise RankedError("Không tìm thấy cuộc đua này.", 404)
    if row["expires_at"] < _now():
        raise RankedError("Cuộc đua này đã hết hạn (7 ngày sau khi tạo).", 410)
    return row


def create_race(level: str, nickname: str, device_id: str, client: Optional[str]) -> dict:
    nickname, _ = _clean_identity(nickname, device_id)
    _race_limiter.take(client)
    now = _now()
    seed = secrets.randbits(32)
    with closing(_connect()) as con, _db_lock:
        _purge(con)
        for _ in range(20):
            code = "".join(secrets.choice(rooms.CODE_ALPHABET) for _ in range(rooms.CODE_LEN))
            try:
                con.execute("INSERT INTO races VALUES (?,?,?,?,?,?)",
                            (code, seed, level, nickname, now, now + RACE_TTL_S))
                break
            except sqlite3.IntegrityError:
                continue
        else:  # pragma: no cover
            raise RankedError("Không tạo được cuộc đua, hãy thử lại.", 503)
        con.commit()
    return {"code": code, "seed": seed, "level": level}


def _race_results(con: sqlite3.Connection, code: str, device_hash: Optional[str] = None) -> list[dict]:
    rows = con.execute(
        """WITH best AS (
               SELECT *, ROW_NUMBER() OVER (PARTITION BY device_hash
                                            ORDER BY score DESC, duration_s ASC, id ASC) AS rn
               FROM runs WHERE race = ? AND kind = 'race' AND status = 'verified')
           SELECT nickname, device_hash, score, locks, mistakes, duration_s, finished_at FROM best WHERE rn = 1
           ORDER BY score DESC, duration_s ASC, id ASC""", (code,)).fetchall()
    out = []
    for i, r in enumerate(rows, 1):
        row = {"rank": i, "nickname": r["nickname"], "score": r["score"], "locks": r["locks"],
               "mistakes": r["mistakes"], "duration_s": r["duration_s"], "finished_at": int(r["finished_at"])}
        if device_hash is not None:
            row["you"] = r["device_hash"] == device_hash  # nicknames are not unique, so mark the caller's own row
        out.append(row)
    return out


def _race_view(con: sqlite3.Connection, race: sqlite3.Row, device_hash: Optional[str] = None) -> dict:
    playing = con.execute(
        "SELECT COUNT(*) FROM runs WHERE race = ? AND status = 'open' AND created_at >= ?",
        (race["code"], _now() - RUN_TTL_S)).fetchone()[0]
    return {"code": race["code"], "level": race["level"], "created_by": race["created_by"],
            "created_at": int(race["created_at"]), "expires_at": int(race["expires_at"]),
            "results": _race_results(con, race["code"], device_hash), "playing": playing}


def race_info(code: str, device_id: Optional[str] = None) -> dict:
    """The race with its results. With a valid ``device_id`` every result row gets ``you`` (true for the
    caller's own best run); without one the field is left out."""
    device_hash = _device_hash(device_id) if isinstance(device_id, str) and _DEVICE_RE.match(device_id) else None
    with closing(_connect()) as con:
        return _race_view(con, _load_race(con, code), device_hash)


# --------------------------------------------------------------------------- runs


def create_run(kind: str, level: Optional[str], nickname: str, device_id: str, race: Optional[str],
               client: Optional[str]) -> dict:
    nickname, device_hash = _clean_identity(nickname, device_id)
    if kind == "race" and not race:
        raise RankedError("Thiếu mã cuộc đua.", 422)
    if kind == "ranked":
        if race:
            raise RankedError("Ván xếp hạng không có mã cuộc đua.", 422)
        if level not in LEVELS:
            raise RankedError("Thiếu cấp độ.", 422)
    _run_limiter.take(client)
    run_id, token = secrets.token_hex(8), secrets.token_hex(16)
    now = _now()
    with closing(_connect()) as con, _db_lock:
        race_code = None
        if kind == "race":
            row = _load_race(con, race)  # before the purge, so an expired race answers 410, not 404
            _purge(con)
            race_code, level, seed = row["code"], row["level"], row["seed"]
            taken = con.execute("SELECT COUNT(*) FROM runs WHERE race = ?", (race_code,)).fetchone()[0]
            if taken >= MAX_RACE_RUNS:
                raise RankedError(f"Cuộc đua đã đủ {MAX_RACE_RUNS} lượt chơi.", 410)
        else:
            _purge(con)
            seed = secrets.randbits(32)
        con.execute("INSERT INTO runs (id, token_hash, kind, race, level, seed, nickname, device_hash, created_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?)",
                    (run_id, rooms._hash(token), kind, race_code, level, seed, nickname, device_hash, now))
        con.commit()
    out = {"run_id": run_id, "run_token": token, "seed": seed, "level": level, "kind": kind}
    if race_code:
        out["race"] = race_code
    return out


def _open_run(con: sqlite3.Connection, run_id: Any, token: Any) -> Optional[sqlite3.Row]:
    """The run when the id/token pair is valid, still open and younger than 3 hours; else None."""
    if not isinstance(run_id, str) or not _RUN_RE.match(run_id) or not isinstance(token, str) \
            or not token or len(token) > 64:
        return None
    row = con.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    if row is None or row["status"] != "open" or row["created_at"] < _now() - RUN_TTL_S:
        return None
    if not hmac.compare_digest(rooms._hash(token), row["token_hash"]):
        return None
    return row


def serve_puzzle(run_id: Any, token: Any, *, kind: str, topic: Optional[str], tier: Optional[int],
                 template_id: Optional[str]) -> Optional[tuple[dict, str]]:
    """The deterministic puzzle for a valid run (and the run's level), recorded as served.

    ``None`` when the run fields are missing/invalid or the run database is unusable (the caller then
    serves a normal random puzzle). Bank errors (no matching puzzle) propagate like on a normal request.
    The client's exclude lists are ignored: the server's own history is used, which is what an honest
    client sends anyway.
    """
    if not run_id or not token:
        return None
    try:
        with closing(_connect()) as con, _db_lock:
            run = _open_run(con, run_id, token)
            if run is None:
                return None
            cnt = con.execute("SELECT COUNT(*) FROM served WHERE run_id = ?", (run["id"],)).fetchone()[0]
            if cnt >= MAX_SERVED_PER_RUN:
                return None
            n = con.execute(
                "SELECT COUNT(*) FROM served WHERE run_id = ? AND kind = ? AND req_topic IS ? "
                "AND req_tier IS ? AND req_template IS ?", (run["id"], kind, topic, tier, template_id)).fetchone()[0]
            hist = con.execute("SELECT puzzle_id, template_id FROM served WHERE run_id = ? "
                               "ORDER BY seq DESC LIMIT ?", (run["id"], HISTORY_IDS)).fetchall()
            rng = random.Random(f"{run['seed']}:{kind}:{topic}:{tier}:{template_id}:{n}")
            row = bank.select_puzzle(
                kind=kind, topic=topic, tier=tier, level=run["level"], template_id=template_id,
                exclude_ids=[h["puzzle_id"] for h in hist],
                exclude_templates=[h["template_id"] for h in hist[:HISTORY_TEMPLATES]], rng=rng)
            con.execute("INSERT INTO served (run_id, seq, puzzle_id, kind, req_topic, req_tier, req_template, "
                        "topic, template_id) VALUES (?,?,?,?,?,?,?,?,?)",
                        (run["id"], cnt + 1, row["id"], kind, topic, tier, template_id,
                         row["topic"], row["template_id"]))
            con.commit()
            return row, run["level"]
    except bank.BankError:
        raise
    except Exception:  # noqa: BLE001 - recording must never break serving puzzles
        return None


def record_hint(run_id: Any, token: Any, puzzle_id: str, level: int) -> None:
    """Remember the highest hint level opened for a puzzle served in this run. Never raises."""
    if not run_id or not token:
        return
    try:
        with closing(_connect()) as con, _db_lock:
            run = _open_run(con, run_id, token)
            if run is None:
                return
            con.execute(
                "UPDATE served SET hint = MAX(hint, ?) WHERE run_id = ? AND seq = "
                "(SELECT MIN(seq) FROM served WHERE run_id = ? AND puzzle_id = ?)",
                (level, run["id"], run["id"], puzzle_id))
            con.commit()
    except Exception:  # noqa: BLE001
        return


def record_answer(run_id: Any, token: Any, puzzle_id: str, correct: bool) -> None:
    """Remember the server-checked result of the first answer to a puzzle served in this run. Never raises."""
    if not run_id or not token:
        return
    try:
        with closing(_connect()) as con, _db_lock:
            run = _open_run(con, run_id, token)
            if run is None:
                return
            con.execute(
                "UPDATE served SET correct = ? WHERE run_id = ? AND correct IS NULL AND seq = "
                "(SELECT MIN(seq) FROM served WHERE run_id = ? AND puzzle_id = ?)",
                (1 if correct else 0, run["id"], run["id"], puzzle_id))
            con.commit()
    except Exception:  # noqa: BLE001
        return


# --------------------------------------------------------------------------- finish


def _records(con: sqlite3.Connection, run_id: str) -> list[dict]:
    out = []
    for r in con.execute("SELECT * FROM served WHERE run_id = ? ORDER BY seq", (run_id,)):
        out.append({"id": r["puzzle_id"], "seq": r["seq"], "kind": r["kind"], "req_topic": r["req_topic"],
                    "req_tier": r["req_tier"], "req_template": r["req_template"], "topic": r["topic"],
                    "template_id": r["template_id"], "hint": r["hint"],
                    "correct": None if r["correct"] is None else bool(r["correct"])})
    return out


def finish_run(run_id: str, token: str, moves: list, client_score: Optional[int]) -> dict:
    with closing(_connect()) as con:
        run = con.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone() \
            if _RUN_RE.match(run_id or "") else None
        if run is None:
            raise RankedError("Không tìm thấy ván chơi này.", 404)
        if not token or len(token) > 64 or not hmac.compare_digest(rooms._hash(token), run["token_hash"]):
            raise RankedError("Sai mã ván chơi.", 403)
        if run["status"] != "open":
            raise RankedError("Ván chơi này đã được gửi kết quả.", 409)
        if run["created_at"] < _now() - RUN_TTL_S:
            raise RankedError("Ván chơi này đã quá 3 giờ nên không thể gửi kết quả.", 410)
        records = _records(con, run_id)

    reason: Optional[str] = None
    summary: Optional[dict] = None
    try:
        summary = rescue_engine.replay(run["seed"], run["level"], moves, records)
    except rescue_engine.Rejected as e:
        reason = e.reason
    status = "verified" if summary else "rejected"

    finished = _now()
    duration = round(max(0.0, finished - run["created_at"]), 1)
    s = summary or {}
    with closing(_connect()) as con, _db_lock:
        cur = con.execute(
            "UPDATE runs SET status = ?, reason = ?, finished_at = ?, duration_s = ?, score = ?, locks = ?, "
            "mistakes = ?, bugs_fixed = ?, best_streak = ?, client_score = ? WHERE id = ? AND status = 'open'",
            (status, reason, finished, duration, s.get("score", 0), s.get("locks", 0), s.get("mistakes", 0),
             s.get("bugs_fixed", 0), s.get("best_streak", 0), client_score, run_id))
        if cur.rowcount == 0:
            raise RankedError("Ván chơi này đã được gửi kết quả.", 409)
        con.commit()
        if summary is None:
            return {"status": "rejected", "reason": reason}
        out = {"status": "verified", "score": s["score"], "locks": s["locks"], "mistakes": s["mistakes"],
               "bugs_fixed": s["bugs_fixed"], "best_streak": s["best_streak"], "duration_s": duration,
               "rank": None}
        if run["kind"] == "ranked":
            if s["score"] > 0:
                ranks = {p: _rank_of(con, run["level"], p, run["device_hash"]) for p in PERIODS}
                out["rank"] = {p: (v["rank"] if v else None) for p, v in ranks.items()}
        else:
            race = con.execute("SELECT * FROM races WHERE code = ?", (run["race"],)).fetchone()
            if race is not None:
                out["race"] = _race_view(con, race, run["device_hash"])
        return out


# --------------------------------------------------------------------------- leaderboard


def period_start(period: str, now: Optional[float] = None) -> float:
    """Start of the current Vietnam-time day or week (Monday) as a Unix timestamp; 0 for ``all``."""
    if period == "all":
        return 0.0
    dt = datetime.fromtimestamp(_now() if now is None else now, VN_TZ).replace(hour=0, minute=0, second=0,
                                                                              microsecond=0)
    if period == "week":
        dt -= timedelta(days=dt.weekday())
    return dt.timestamp()


_BEST = """WITH best AS (
    SELECT id, nickname, device_hash, score, locks, finished_at,
           ROW_NUMBER() OVER (PARTITION BY device_hash ORDER BY score DESC, finished_at ASC, id ASC) AS rn
    FROM runs WHERE kind = 'ranked' AND status = 'verified' AND level = ? AND finished_at >= ? AND score > 0)
"""


def _rank_of(con: sqlite3.Connection, level: str, period: str, device_hash: str) -> Optional[dict]:
    since = period_start(period)
    mine = con.execute(_BEST + "SELECT * FROM best WHERE rn = 1 AND device_hash = ?",
                       (level, since, device_hash)).fetchone()
    if mine is None:
        return None
    ahead = con.execute(
        _BEST + "SELECT COUNT(*) FROM best WHERE rn = 1 AND (score > ? OR (score = ? AND "
        "(finished_at < ? OR (finished_at = ? AND id < ?))))",
        (level, since, mine["score"], mine["score"], mine["finished_at"], mine["finished_at"], mine["id"])
    ).fetchone()[0]
    return {"rank": ahead + 1, "score": mine["score"]}


def leaderboard(level: str, period: str, device_id: Optional[str] = None) -> dict:
    with closing(_connect()) as con:
        rows = con.execute(
            _BEST + "SELECT nickname, score, locks, finished_at FROM best WHERE rn = 1 "
            "ORDER BY score DESC, finished_at ASC, id ASC LIMIT ?",
            (level, period_start(period), LEADERBOARD_SIZE)).fetchall()
        you = None
        if isinstance(device_id, str) and _DEVICE_RE.match(device_id):
            you = _rank_of(con, level, period, _device_hash(device_id))
    entries = [{"rank": i, "nickname": r["nickname"], "score": r["score"], "locks": r["locks"],
                "at": int(r["finished_at"])} for i, r in enumerate(rows, 1)]
    return {"level": level, "period": period, "entries": entries, "you": you}


# --------------------------------------------------------------------------- PvP rating (Elo, docs/pvp.md section 6)


def pvp_rating(device_hash: Optional[str]) -> int:
    """The Elo rating of a device (1000 until its first rated match). Never raises."""
    if not device_hash:
        return PVP_START_RATING
    try:
        with closing(_connect()) as con:
            row = con.execute("SELECT rating FROM pvp_ratings WHERE device_hash = ?", (device_hash,)).fetchone()
        return row["rating"] if row else PVP_START_RATING
    except Exception:  # noqa: BLE001 - a rating must never break a lobby
        return PVP_START_RATING


def pvp_apply_result(hash_a: str, hash_b: str, score_a: float) -> Optional[tuple[tuple[int, int], tuple[int, int]]]:
    """Update both devices after a human-vs-human match (``score_a``: 1 win, 0.5 draw, 0 loss for A). Returns
    ``((before_a, after_a), (before_b, after_b))``, or None when the rating database is unusable."""
    try:
        with closing(_connect()) as con, _db_lock:
            ra = _rating_row(con, hash_a)
            rb = _rating_row(con, hash_b)
            exp_a = 1 / (1 + 10 ** ((rb - ra) / 400))
            new_a = ra + round(PVP_ELO_K * (score_a - exp_a))
            new_b = rb + round(PVP_ELO_K * ((1 - score_a) - (1 - exp_a)))
            now = _now()
            for h, before, after, won, lost in ((hash_a, ra, new_a, score_a == 1, score_a == 0),
                                                (hash_b, rb, new_b, score_a == 0, score_a == 1)):
                con.execute(
                    "INSERT INTO pvp_ratings (device_hash, rating, games, wins, losses, updated_at) "
                    "VALUES (?,?,1,?,?,?) ON CONFLICT(device_hash) DO UPDATE SET rating = excluded.rating, "
                    "games = games + 1, wins = wins + excluded.wins, losses = losses + excluded.losses, "
                    "updated_at = excluded.updated_at", (h, after, int(won), int(lost), now))
            con.commit()
        return (ra, new_a), (rb, new_b)
    except Exception:  # noqa: BLE001
        return None


def _rating_row(con: sqlite3.Connection, device_hash: str) -> int:
    row = con.execute("SELECT rating FROM pvp_ratings WHERE device_hash = ?", (device_hash,)).fetchone()
    return row["rating"] if row else PVP_START_RATING


# --------------------------------------------------------------------------- Misaki ladder (docs/pvp.md section 5.2)


def _unlocked(wins: dict[int, int]) -> int:
    """Level 1 is always open; beating level n opens n + 1 (up to the last one)."""
    beaten = [lv for lv, n in wins.items() if n > 0]
    return min(MISAKI_LEVELS, max(beaten, default=0) + 1)


def misaki_progress(device_hash: Optional[str]) -> dict:
    """``{"unlocked": n, "wins": {"1": k, ...}, "games": {"1": k, ...}}`` for a device (all four levels listed).
    Never raises: an unusable database reads as a fresh device (level 1 only)."""
    wins = {lv: 0 for lv in range(1, MISAKI_LEVELS + 1)}
    games = dict(wins)
    if device_hash:
        try:
            with closing(_connect()) as con:
                for row in con.execute("SELECT level, games, wins FROM misaki_progress WHERE device_hash = ?",
                                       (device_hash,)):
                    if row["level"] in wins:
                        wins[row["level"]], games[row["level"]] = row["wins"], row["games"]
        except Exception:  # noqa: BLE001 - progress must never break a lobby
            pass
    return {"unlocked": _unlocked(wins), "wins": {str(k): v for k, v in wins.items()},
            "games": {str(k): v for k, v in games.items()}}


def misaki_unlocked(device_hash: Optional[str]) -> int:
    return misaki_progress(device_hash)["unlocked"]


def misaki_record(device_hash: Optional[str], level: int, won: bool) -> Optional[int]:
    """Count a finished normal (non-training) match against Misaki ``level``. Returns the level this win newly
    unlocked (``level + 1``), or None. Never raises."""
    if not device_hash or not 1 <= level <= MISAKI_LEVELS:
        return None
    try:
        with closing(_connect()) as con, _db_lock:
            before = misaki_progress(device_hash)["unlocked"]
            con.execute(
                "INSERT INTO misaki_progress (device_hash, level, games, wins, updated_at) VALUES (?,?,1,?,?) "
                "ON CONFLICT(device_hash, level) DO UPDATE SET games = games + 1, wins = wins + excluded.wins, "
                "updated_at = excluded.updated_at", (device_hash, level, int(won), _now()))
            con.commit()
        after = misaki_progress(device_hash)["unlocked"]
        return after if after > before else None
    except Exception:  # noqa: BLE001
        return None
