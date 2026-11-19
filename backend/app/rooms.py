"""Live classroom rooms: a teacher opens a room, students join with a nickname and play as usual,
and the teacher's dashboard shows what the class is getting wrong.

Trust model: correctness and the named mistake are computed by the server when ``/api/puzzle/{id}/answer``
checks an answer (``log_answer`` is called from there and nowhere else). The only client-reported data
is the leaderboard (score / status / bugs fixed via ``progress``), and even that is capped on the server:
the board shows the in-game score the browser reports, but ``record_progress`` stores
``min(reported score, score_ceiling(...))``, a ceiling derived from the correct answers the server itself
logged for that player (``bugs_fixed`` is capped by the same count). An honest score is never clipped; a
faked one cannot exceed what those verified answers could ever earn in Code Rescue (see ``score_ceiling``).
It is a ceiling, not a replay: a cheater who really answered many puzzles can still post up to it, but 99999
with a handful of answers is stored as the ceiling. Exact verification is what ranked runs and races do
(``ranked.py``). Syntax Rows has no room plumbing (no room or token on its endpoints, and ``progress`` only
means Code Rescue), so there is nothing to bound there. Only nicknames are stored, in their
own SQLite file next to the custom-sets file (``rooms.sqlite``). A room expires 12 hours after its
last student activity (create, join, answer, progress); expired rooms are purged lazily.
"""
from __future__ import annotations

import hashlib
import hmac
import math
import os
import re
import secrets
import sqlite3
import tempfile
import threading
import time
import unicodedata
from contextlib import closing
from pathlib import Path
from typing import Optional

import yaml

from . import bank, custom, nicknames, rescue_engine
from . import i18n
from .i18n import tr

DB_PATH = Path(os.environ.get("SYNTAX_STACK_ROOMS_DB", custom.DB_PATH.parent / "rooms.sqlite"))
TTL_S = 12 * 3600
RATE_LIMIT = 5              # new rooms per client per window
RATE_WINDOW_S = 3600
MAX_TRACKED_CLIENTS = 20_000
MAX_PLAYERS = 60
MAX_ANSWERS_PER_PLAYER = 1000   # keeps a spamming client from growing the file without bound
MAX_ANSWERS_PER_ROOM = 20_000
MAX_NICKNAME = 20
MAX_TITLE = 40
NAME_MODES = ("random", "free")
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
CODE_LEN = 5

TOPICS = ("variables", "conditions", "loops", "functions")
TYPES = ("fill_blank", "predict_output", "parsons", "find_bug")
STATUSES = ("playing", "crash", "nofit")
_TYPE_SUFFIX = {"fill": "fill_blank", "predict": "predict_output", "parsons": "parsons", "bug": "find_bug"}

GROUP_LABELS = {
    "output_mismatch": "Sai kết quả đầu ra", "wrong_order": "Sai thứ tự", "bad_indent": "Sai thụt lề",
    "syntax": "Lỗi cú pháp", "wrong_fix": "Sửa sai dòng", "wrong_line": "Sửa nhầm dòng",
    "runtime": "Lỗi khi chạy", "wrong_choice": "Chọn sai đáp án", "other": "Lỗi khác",
}
GROUP_LABELS_EN = {
    "output_mismatch": "Wrong output", "wrong_order": "Wrong order", "bad_indent": "Wrong indentation",
    "syntax": "Syntax error", "wrong_fix": "Wrong fix", "wrong_line": "Fixed the wrong line",
    "runtime": "Error while running", "wrong_choice": "Wrong choice", "other": "Other mistake",
}
MISTAKES_FILE = Path(__file__).resolve().parents[1] / "content" / "mistakes.yaml"
LABEL_MAX = 60

_CODE_RE = re.compile(rf"^[{CODE_ALPHABET}]{{{CODE_LEN}}}$")


class RoomError(bank.BankError):
    """An error with an explicit HTTP status; the message (Vietnamese or English, by the request) is shown to the user."""

    def __init__(self, message: str, status: int):
        super().__init__(message)
        self.status = status


def _now() -> float:
    return time.time()


# --------------------------------------------------------------------------- labels


_notes: Optional[dict] = None
_notes_en: dict = {}


def _mistake_notes() -> dict:
    """The Vietnamese notes (content/mistakes.yaml); the ``<name>_en`` siblings are kept apart in ``_notes_en``."""
    global _notes, _notes_en
    if _notes is None:
        try:
            _notes, _notes_en = i18n.split_en(yaml.safe_load(MISTAKES_FILE.read_text(encoding="utf-8")) or {})
        except (OSError, yaml.YAMLError):
            _notes, _notes_en = {}, {}
    return _notes


LABELS_FILE = MISTAKES_FILE.with_name("mistake_labels.yaml")
_labels: Optional[dict] = None
_labels_en: dict = {}


def _mistake_labels() -> dict:
    """Hand-written short labels for the projector (content/mistake_labels.yaml, Vietnamese; the English ones are the
    ``<name>_en`` siblings, kept apart in ``_labels_en``)."""
    global _labels, _labels_en
    if _labels is None:
        try:
            _labels, _labels_en = i18n.split_en(yaml.safe_load(LABELS_FILE.read_text(encoding="utf-8")) or {})
        except (OSError, yaml.YAMLError):
            _labels, _labels_en = {}, {}
    return _labels


def _short(text: str) -> str:
    text = text.strip()
    if ":" in text:
        text = text.split(":", 1)[0]
    else:
        text = re.split(r"(?<=[.!?])\s", text, maxsplit=1)[0]
    text = text.strip().rstrip(".!?").strip()
    return text if len(text) <= LABEL_MAX else text[:LABEL_MAX - 1].rstrip() + "…"


def mistake_label(key: Optional[str], lang: Optional[str] = None) -> str:
    """Short label for a mistake key (a named mistake or an error group), in Vietnamese or English."""
    if i18n.resolve(lang) == "en":
        if not key:
            return GROUP_LABELS_EN["other"]
        _mistake_labels(), _mistake_notes()  # load
        label = _labels_en.get(key)
        if isinstance(label, str) and label.strip():
            return label.strip()
        note = _notes_en.get(key)
        if isinstance(note, str) and note.strip():
            return _short(note)
        return GROUP_LABELS_EN.get(key, GROUP_LABELS_EN["other"])
    if not key:
        return GROUP_LABELS["other"]
    label = _mistake_labels().get(key)
    if isinstance(label, str) and label.strip():
        return label.strip()
    note = _mistake_notes().get(key)
    if isinstance(note, str) and note.strip():
        return _short(note)
    if key in GROUP_LABELS:
        return GROUP_LABELS[key]
    return GROUP_LABELS["other"]


# --------------------------------------------------------------------------- rate limit

_rate_lock = threading.Lock()
_hits: dict[str, list[float]] = {}


def client_key(client: Optional[str]) -> str:
    return hashlib.sha256(("syntax-stack-rooms:" + (client or "unknown")).encode()).hexdigest()[:16]


def reset_rate_limits() -> None:
    with _rate_lock:
        _hits.clear()


def _take_slot(key: str) -> None:
    now = _now()
    with _rate_lock:
        if len(_hits) > MAX_TRACKED_CLIENTS:
            for k in [k for k, v in _hits.items() if not v or v[-1] < now - RATE_WINDOW_S]:
                del _hits[k]
        recent = [t for t in _hits.get(key, []) if t > now - RATE_WINDOW_S]
        if len(recent) >= RATE_LIMIT:
            _hits[key] = recent
            raise RoomError(
                tr(f"Bạn đã mở {RATE_LIMIT} phòng học trong một giờ qua, đó là mức tối đa. Hãy thử lại sau.",
                   f"You opened {RATE_LIMIT} classrooms in the last hour, which is the maximum. Please try again later."),
                429)
        recent.append(now)
        _hits[key] = recent


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
            _db_path_cache = Path(tempfile.gettempdir()) / "syntax-stack-rooms.sqlite"
        return _db_path_cache


_SCHEMA = """
CREATE TABLE IF NOT EXISTS rooms (
    code TEXT PRIMARY KEY, teacher_hash TEXT NOT NULL, level TEXT NOT NULL, title TEXT NOT NULL,
    created_at REAL NOT NULL, last_activity REAL NOT NULL, open INTEGER NOT NULL DEFAULT 1,
    names TEXT NOT NULL DEFAULT 'random');
CREATE TABLE IF NOT EXISTS players (
    id TEXT PRIMARY KEY, room TEXT NOT NULL, nickname TEXT NOT NULL, token_hash TEXT NOT NULL,
    joined_at REAL NOT NULL, last_seen REAL NOT NULL,
    score INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'playing',
    bugs_fixed INTEGER NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS idx_players_room ON players (room);
CREATE TABLE IF NOT EXISTS answers (
    id INTEGER PRIMARY KEY AUTOINCREMENT, room TEXT NOT NULL, player_id TEXT NOT NULL,
    puzzle_id TEXT NOT NULL, template_id TEXT NOT NULL, topic TEXT NOT NULL, type TEXT NOT NULL,
    correct INTEGER NOT NULL, mistake_key TEXT, ts REAL NOT NULL, tier INTEGER);
CREATE INDEX IF NOT EXISTS idx_answers_room ON answers (room);
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
            cols = [r["name"] for r in con.execute("PRAGMA table_info(rooms)")]
            if "names" not in cols:  # file from before generated nicknames: those rooms used free names
                con.execute("ALTER TABLE rooms ADD COLUMN names TEXT NOT NULL DEFAULT 'free'")
            if "tier" not in [r["name"] for r in con.execute("PRAGMA table_info(answers)")]:
                con.execute("ALTER TABLE answers ADD COLUMN tier INTEGER")  # older rows stay NULL = counted as tier 3
            _ready.add(key)
    return con


def _hash(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def _purge(con: sqlite3.Connection) -> None:
    cutoff = _now() - TTL_S
    con.execute("DELETE FROM rooms WHERE last_activity < ?", (cutoff,))
    con.execute("DELETE FROM players WHERE room NOT IN (SELECT code FROM rooms)")
    con.execute("DELETE FROM answers WHERE room NOT IN (SELECT code FROM rooms)")


def _wipe(con: sqlite3.Connection, code: str) -> None:
    for table, col in (("answers", "room"), ("players", "room"), ("rooms", "code")):
        con.execute(f"DELETE FROM {table} WHERE {col} = ?", (code,))


def _normalize_code(code: str) -> str:
    return (code or "").strip().upper()


def _load_room(con: sqlite3.Connection, code: str) -> sqlite3.Row:
    """The room row, or a 404 (unknown, malformed, or expired; an expired room is deleted on the spot)."""
    code = _normalize_code(code)
    row = con.execute("SELECT * FROM rooms WHERE code = ?", (code,)).fetchone() if _CODE_RE.match(code) else None
    if row is None:
        raise RoomError(tr("Không tìm thấy phòng học này.", "This classroom was not found."), 404)
    if row["last_activity"] < _now() - TTL_S:
        _wipe(con, code)
        con.commit()
        raise RoomError(tr("Phòng học này đã hết hạn (12 giờ sau lần hoạt động cuối).",
                           "This classroom has expired (12 hours after its last activity)."), 404)
    return row


def _check_teacher(row: sqlite3.Row, teacher_key: Optional[str]) -> None:
    if not teacher_key or not hmac.compare_digest(_hash(teacher_key), row["teacher_hash"]):
        raise RoomError(tr("Sai mã giáo viên.", "Wrong teacher key."), 403)


def _clean_text(text: str, limit: int, what, *, required: bool) -> str:
    """``what`` names the field in the message: a Vietnamese string, or a ``(Vietnamese, English)`` pair."""
    vi, en = (what, what) if isinstance(what, str) else what
    text = (text or "").strip()
    if any(unicodedata.category(ch).startswith("C") for ch in text):
        raise RoomError(tr(f"{vi} không được chứa ký tự điều khiển.", f"{en} must not contain control characters."), 422)
    if required and not text:
        raise RoomError(tr(f"{vi} không được để trống.", f"{en} must not be empty."), 422)
    if len(text) > limit:
        raise RoomError(tr(f"{vi} tối đa {limit} ký tự.", f"{en} can be at most {limit} characters."), 422)
    return text


# --------------------------------------------------------------------------- public API


def create_room(level: str, title: Optional[str], client: Optional[str], names: str = "random") -> dict:
    if names not in NAME_MODES:
        raise RoomError(tr("Chế độ đặt tên không hợp lệ.", "That naming mode is not valid."), 422)
    title = _clean_text(title or "", MAX_TITLE, ("Tên phòng", "Room name"), required=False)
    _take_slot(client_key(client))
    teacher_key = secrets.token_hex(16)
    now = _now()
    with closing(_connect()) as con, _db_lock:
        _purge(con)
        for _ in range(20):
            code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LEN))
            try:
                con.execute("INSERT INTO rooms (code, teacher_hash, level, title, created_at, last_activity, open, names) "
                            "VALUES (?,?,?,?,?,?,1,?)",
                            (code, _hash(teacher_key), level, title, now, now, names))
                break
            except sqlite3.IntegrityError:
                continue
        else:  # pragma: no cover
            raise RoomError(tr("Không tạo được phòng học, hãy thử lại.", "Could not create the classroom, please try again."), 503)
        con.commit()
    return {"code": code, "teacher_key": teacher_key, "level": level, "title": title, "names": names}


def room_info(code: str) -> dict:
    with closing(_connect()) as con:
        row = _load_room(con, code)
        players = con.execute("SELECT COUNT(*) FROM players WHERE room = ?", (row["code"],)).fetchone()[0]
    return {"code": row["code"], "level": row["level"], "title": row["title"],
            "open": bool(row["open"]), "players": players, "names": row["names"]}


def join_room(code: str, nickname: Optional[str]) -> dict:
    with closing(_connect()) as con, _db_lock:
        _purge(con)
        room = _load_room(con, code)
        random_mode = room["names"] == "random"
        if not random_mode:
            nickname = _clean_text(nickname or "", MAX_NICKNAME, ("Biệt danh", "Nickname"), required=True)
            if not nicknames.is_allowed_free(nickname):
                raise RoomError(tr("Biệt danh này không được dùng. Hãy chọn tên khác.",
                                   "This nickname can't be used. Please pick another one."), 422)
        if not room["open"]:
            raise RoomError(tr("Phòng học này đã đóng.", "This classroom is closed."), 410)
        existing = [r["nickname"].casefold() for r in
                    con.execute("SELECT nickname FROM players WHERE room = ?", (room["code"],))]
        if len(existing) >= MAX_PLAYERS:
            raise RoomError(tr(f"Phòng học đã đủ {MAX_PLAYERS} người.",
                               f"The classroom is full ({MAX_PLAYERS} players)."), 409)
        if random_mode:
            for _ in range(200):
                final = nicknames.generate()
                if final.casefold() not in existing:
                    break
            else:  # pragma: no cover - 60 players against ~60k names
                raise RoomError(tr("Không tạo được biệt danh, hãy thử lại.",
                                   "Could not make a nickname, please try again."), 503)
        else:
            final, n = nickname, 1
            while final.casefold() in existing:
                n += 1
                final = f"{nickname} {n}"
        player_id = "p" + secrets.token_hex(4)
        token = secrets.token_hex(16)
        now = _now()
        con.execute("INSERT INTO players (id, room, nickname, token_hash, joined_at, last_seen) "
                    "VALUES (?,?,?,?,?,?)", (player_id, room["code"], final, _hash(token), now, now))
        con.execute("UPDATE rooms SET last_activity = ? WHERE code = ?", (now, room["code"]))
        con.commit()
    return {"player_id": player_id, "player_token": token, "nickname": final, "level": room["level"]}


def kick_player(code: str, player_id: str, teacher_key: Optional[str]) -> None:
    """Remove a player and all their answers. Their token stops working; they can only rejoin as a new player."""
    with closing(_connect()) as con, _db_lock:
        room = _load_room(con, code)
        _check_teacher(room, teacher_key)
        row = con.execute("SELECT id FROM players WHERE room = ? AND id = ?",
                          (room["code"], player_id or "")).fetchone()
        if row is None:
            raise RoomError(tr("Không tìm thấy người chơi này.", "This player was not found."), 404)
        con.execute("DELETE FROM answers WHERE room = ? AND player_id = ?", (room["code"], row["id"]))
        con.execute("DELETE FROM players WHERE id = ?", (row["id"],))
        con.commit()


def _find_player(con: sqlite3.Connection, code: str, token: str) -> Optional[sqlite3.Row]:
    return con.execute("SELECT * FROM players WHERE room = ? AND token_hash = ?",
                       (code, _hash(token))).fetchone()


def log_answer(room_code: str, token: str, puzzle: dict, option_id: Optional[str], result: dict) -> None:
    """Record one server-checked answer. Never raises: a logging problem must not touch the answer."""
    try:
        code = _normalize_code(room_code)
        if not _CODE_RE.match(code) or not token or len(token) > 64:
            return
        ptype = puzzle["type"]
        mistake = None
        if not result["correct"]:
            if ptype != "parsons":
                opt = next((o for o in puzzle["data"]["options"] if o["id"] == option_id), None)
                mistake = (opt or {}).get("name")
            mistake = mistake or result.get("error_group") or "other"
        topic = puzzle["topic"]
        suffix = puzzle["template_id"].rsplit("_", 1)[-1]
        ptype = _TYPE_SUFFIX.get(suffix, ptype)
        now = _now()
        with closing(_connect()) as con, _db_lock:
            room = con.execute("SELECT open, last_activity FROM rooms WHERE code = ?", (code,)).fetchone()
            if room is None or not room["open"] or room["last_activity"] < now - TTL_S:
                return
            player = _find_player(con, code, token)
            if player is None:
                return
            mine = con.execute("SELECT COUNT(*) FROM answers WHERE room = ? AND player_id = ?",
                               (code, player["id"])).fetchone()[0]
            if mine >= MAX_ANSWERS_PER_PLAYER:
                return
            total = con.execute("SELECT COUNT(*) FROM answers WHERE room = ?", (code,)).fetchone()[0]
            if total >= MAX_ANSWERS_PER_ROOM:
                return
            con.execute("INSERT INTO answers (room, player_id, puzzle_id, template_id, topic, type, correct, "
                        "mistake_key, ts, tier) VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (code, player["id"], puzzle["id"], puzzle["template_id"], topic, ptype,
                         1 if result["correct"] else 0, mistake, now, puzzle.get("tier")))
            con.execute("UPDATE players SET last_seen = ? WHERE id = ?", (now, player["id"]))
            con.execute("UPDATE rooms SET last_activity = ? WHERE code = ?", (now, code))
            con.commit()
    except Exception:  # noqa: BLE001 - deliberately broad, see docstring
        return


# --------------------------------------------------------------------------- score ceiling

# The same puzzle can be served again in one run only after 500 others (the browser sends the last 500 seen ids,
# main.js ``G.seenIds.slice(-500)``), so a player with R logged answers can honestly hold at most 1 + R // 500
# correct answers to one puzzle. Anything beyond that is the answer endpoint being replayed, not play.
REPEAT_WINDOW = 500
BOARD_CELLS = rescue_engine.SIZE * rescue_engine.SIZE
_BOMB_CELLS = 9    # a Bomb clears a 3x3 block...
_BOMB_EVERY = 3    # ...and is earned at most once per 3 correct lock answers (the streak reaches 3)


def _answer_ceiling() -> dict[int, int]:
    """The most points one correct answer to a tier-t puzzle can add to a Code Rescue score, for t = 1, 2, 3.

    Read from game.js / rescue_engine.py. A score is the sum of (a) the cells of every placed piece (1 point each)
    and (b) rewards: a lock's ``base * hint factor * streak factor`` and 150 per fixed bug. Last Commit, items and
    wrong answers give no points. Rewards need correct answers: a lock of t = 1, 2 or 3 lines is one answer to a
    tier-t puzzle (Rescue puzzles are picked at exactly the lock's tier), a boss lock (4+ lines, base 700) is two
    tier-3 answers, and a bug fix is one answer to a Debug puzzle (any tier). Best case for a reward: no hint (x1)
    and a streak of 5+ (x2).

    Placement points are bounded by the 8x8 board. It starts empty and holds at most 64 cells, so
    ``cells placed <= 64 + cells cleared``. Cells leave the board only when a lock is answered (<= 8t cells for t
    lines, <= 64 for a boss), a bug line is fixed (<= 64, a failed boss lock), a Bomb is used (<= 9, and at most
    one per 3 correct answers, so 3 per answer) or Last Commit clears 3 rows (<= 24, tier-3 answer, once per run).
    A wrong answer clears nothing in Rescue (the lock turns into a bug line). Undo restores an earlier state
    (grid, tray and score together), so a history with undos is a history without them and can be ignored.

    Per correct answer, tier 1 / 2 / 3:
      lock      100*2 + 8 = 208,   250*2 + 16 = 516,   450*2 + 24 = 924
      boss      (700*2 + 64) / 2 = 732 per tier-3 answer
      bug fix   150 + 64 = 214 (any tier)
    take the largest and add 3 for Bombs: 217, 519, 927."""
    top = rescue_engine.streak_factor(5)
    n = rescue_engine.SIZE
    debug = rescue_engine.BUG_FIX_POINTS + n * n
    out = {}
    for tier in (1, 2, 3):
        best = max(rescue_engine.BASE_POINTS[tier] * top + n * tier, debug)
        if tier == 3:
            best = max(best, math.ceil((rescue_engine.BASE_POINTS[4] * top + n * n) / 2))
        out[tier] = int(best) + _BOMB_CELLS // _BOMB_EVERY
    return out


PER_ANSWER_CEILING = _answer_ceiling()


def counted_correct(answers) -> dict[int, int]:
    """The correct answers that count towards the ceiling, by puzzle tier.

    ``answers``: the player's logged answers as ``(puzzle_id, correct, tier)``, right and wrong. A puzzle counts once
    (plus the repeats ``REPEAT_WINDOW`` allows), so answering one puzzle again and again does not raise the ceiling.
    An unknown tier (a row logged before tiers were stored) counts as tier 3, the loosest."""
    answers = list(answers)
    allowed = 1 + len(answers) // REPEAT_WINDOW
    per_puzzle: dict[str, list[int]] = {}      # puzzle id -> [tier, correct answers so far]
    for pid, correct, tier in answers:
        if correct:
            per_puzzle.setdefault(pid, [tier if tier in (1, 2, 3) else 3, 0])[1] += 1
    out = {1: 0, 2: 0, 3: 0}
    for tier, n in per_puzzle.values():
        out[tier] += min(n, allowed)
    return out


def score_ceiling(correct_by_tier) -> int:
    """The most a Code Rescue run can score, given the player's server-verified correct answers.

    ``correct_by_tier``: ``{1: n1, 2: n2, 3: n3}`` (see ``counted_correct``). Returns
    ``64 + sum(n_t * PER_ANSWER_CEILING[t])``: the 64 is one full board of placements, and every correct answer adds
    at most the reward it can unlock plus the cells it can clear (``_answer_ceiling`` has the derivation). It is an
    upper bound for every legal game and loose on purpose (every lock is the most lucrative one, no hints, a streak
    of 5+); ``tests/test_rooms_ceiling.py`` plays hundreds of games against it.

    Runs: the server cannot tell a player's runs apart (answers and progress carry no run id), but the board shows
    the score of the run being played now. That run's correct answers are a subset of the player's lifetime ones
    and the formula only grows with them, so the ceiling of the lifetime answers bounds every single run (the
    constant 64 is part of each run's own bound, so it is not summed over runs). Practice mode is not covered: it
    clears rows for free when stuck, so its score has no such bound; the browser must report Rescue games only."""
    return BOARD_CELLS + sum(max(0, int(correct_by_tier.get(t, 0))) * v for t, v in PER_ANSWER_CEILING.items())


def record_progress(code: str, token: str, score: int, status: str, bugs_fixed: int) -> None:
    """Store the leaderboard line: ``min(score, score_ceiling)`` and ``bugs_fixed`` capped by the verified correct
    answers (a bug fix needs one). Negative values become 0. ``status`` is validated by the request model."""
    with closing(_connect()) as con, _db_lock:
        room = _load_room(con, code)
        player = _find_player(con, room["code"], token)
        if player is None:
            raise RoomError(tr("Mã người chơi không hợp lệ.", "That player token is not valid."), 403)
        if not room["open"]:
            return  # a closed room keeps its final board
        facts = counted_correct(
            (r["puzzle_id"], r["correct"], r["tier"]) for r in con.execute(
                "SELECT puzzle_id, correct, tier FROM answers WHERE room = ? AND player_id = ?",
                (room["code"], player["id"])))
        score = max(0, min(int(score), score_ceiling(facts)))
        bugs_fixed = max(0, min(int(bugs_fixed), sum(facts.values())))
        now = _now()
        con.execute("UPDATE players SET score = ?, status = ?, bugs_fixed = ?, last_seen = ? WHERE id = ?",
                    (score, status, bugs_fixed, now, player["id"]))
        con.execute("UPDATE rooms SET last_activity = ? WHERE code = ?", (now, room["code"]))
        con.commit()


def close_room(code: str, teacher_key: Optional[str]) -> dict:
    with closing(_connect()) as con, _db_lock:
        room = _load_room(con, code)
        _check_teacher(room, teacher_key)
        con.execute("UPDATE rooms SET open = 0 WHERE code = ?", (room["code"],))
        con.commit()
    return {"open": False}


def delete_room(code: str, teacher_key: Optional[str]) -> None:
    with closing(_connect()) as con, _db_lock:
        room = _load_room(con, code)
        _check_teacher(room, teacher_key)
        _wipe(con, room["code"])
        con.commit()


def summary(code: str, teacher_key: Optional[str]) -> dict:
    now = _now()
    with closing(_connect()) as con:
        room = _load_room(con, code)
        _check_teacher(room, teacher_key)
        players = [dict(r) for r in con.execute("SELECT * FROM players WHERE room = ?", (room["code"],))]
        answers = [dict(r) for r in con.execute(
            "SELECT * FROM answers WHERE room = ? ORDER BY ts, id", (room["code"],))]

    names = {p["id"]: p["nickname"] for p in players}
    per_player: dict[str, list[int]] = {p["id"]: [0, 0] for p in players}
    grid = {t: {ty: {"answers": 0, "correct": 0} for ty in TYPES} for t in TOPICS}
    mistakes: dict[str, dict] = {}
    puzzles: dict[str, dict] = {}
    for a in answers:
        pc = per_player.setdefault(a["player_id"], [0, 0])
        pc[0] += 1
        pc[1] += a["correct"]
        cell = grid.get(a["topic"], {}).get(a["type"])
        if cell is not None:
            cell["answers"] += 1
            cell["correct"] += a["correct"]
        if not a["correct"] and a["mistake_key"]:
            m = mistakes.setdefault(a["mistake_key"], {"count": 0, "topics": {}, "players": set()})
            m["count"] += 1
            m["topics"][a["topic"]] = m["topics"].get(a["topic"], 0) + 1
            m["players"].add(a["player_id"])
        p = puzzles.setdefault(a["puzzle_id"], {"wrong": 0, "correct": 0, "topic": a["topic"], "players": set()})
        if a["correct"]:
            p["correct"] += 1
        else:
            p["wrong"] += 1
            p["players"].add(a["player_id"])

    top_mistakes = [
        {"key": k, "label": mistake_label(k), "count": m["count"],
         "topic": max(m["topics"], key=m["topics"].get), "players": len(m["players"])}
        for k, m in sorted(mistakes.items(), key=lambda kv: (-kv[1]["count"], kv[0]))[:5]]

    unsolved = []
    for pid, p in sorted(puzzles.items(), key=lambda kv: (-kv[1]["wrong"], kv[0])):
        if p["wrong"] < 2 or p["correct"] > 0:
            continue
        try:
            prompt = i18n.pick(bank.get_puzzle(pid), "prompt")
        except bank.BankError:
            prompt = pid
        unsolved.append({"puzzle_id": pid, "prompt": prompt, "topic": p["topic"],
                         "attempts": p["wrong"], "players": len(p["players"])})
        if len(unsolved) == 5:
            break

    recent = [
        {"nickname": names.get(a["player_id"], "?"), "topic": a["topic"], "type": a["type"],
         "correct": bool(a["correct"]),
         "mistake_label": None if a["correct"] else mistake_label(a["mistake_key"]),
         "ago_s": max(0, int(now - a["ts"]))}
        for a in reversed(answers[-10:])]

    board = sorted(
        ({"player_id": p["id"], "nickname": p["nickname"], "score": p["score"], "status": p["status"],
          "answers": per_player[p["id"]][0], "correct": per_player[p["id"]][1],
          "last_seen_s": max(0, int(now - p["last_seen"]))} for p in players),
        key=lambda r: (-r["score"], r["nickname"].casefold()))

    return {
        "code": room["code"], "title": room["title"], "level": room["level"], "open": bool(room["open"]),
        "created_at": int(room["created_at"]),
        "totals": {"players": len(players), "answers": len(answers),
                   "correct": sum(a["correct"] for a in answers)},
        "players": board, "grid": grid, "top_mistakes": top_mistakes, "unsolved": unsolved, "recent": recent,
    }


# --------------------------------------------------------------------------- join URL and QR

_HOST_RE = re.compile(r"^[A-Za-z0-9.\-]+(:\d{1,5})?$|^\[[0-9A-Fa-f:.]+\](:\d{1,5})?$")


def public_base(*, headers, scheme: str, netloc: str) -> str:
    """Absolute base URL of the site. ``SYNTAX_STACK_PUBLIC_URL`` wins; else the forwarded proto/host the
    reverse proxy sends, else the request's own."""
    base = os.getenv("SYNTAX_STACK_PUBLIC_URL", "").strip().rstrip("/")
    if not base:
        proto = (headers.get("x-forwarded-proto") or "").split(",")[0].strip().lower()
        if proto not in ("http", "https"):
            proto = scheme
        host = (headers.get("x-forwarded-host") or "").split(",")[0].strip()
        if not host or not _HOST_RE.match(host):
            host = headers.get("host") or netloc
        base = f"{proto}://{host}"
    return base


def join_url(code: str, *, headers, scheme: str, netloc: str) -> str:
    """Absolute join link for a classroom room."""
    return f"{public_base(headers=headers, scheme=scheme, netloc=netloc)}/?room={code}"


def qr_svg(url: str) -> str:
    import io

    import segno
    buf = io.BytesIO()
    segno.make(url, error="m").save(buf, kind="svg", dark="#141518", light="#ffffff", border=2, scale=8,
                                    xmldecl=False, nl=False)
    return buf.getvalue().decode("utf-8")
