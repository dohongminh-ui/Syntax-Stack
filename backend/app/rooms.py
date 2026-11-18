"""Live classroom rooms: a teacher opens a room, students join with a nickname and play as usual,
and the teacher's dashboard shows what the class is getting wrong.

Trust model: correctness and the named mistake are computed by the server when ``/api/puzzle/{id}/answer``
checks an answer (``log_answer`` is called from there and nowhere else). The only client-reported data
is the leaderboard (score / status / bugs fixed via ``progress``). Only nicknames are stored, in their
own SQLite file next to the custom-sets file (``rooms.sqlite``). A room expires 12 hours after its
last student activity (create, join, answer, progress); expired rooms are purged lazily.
"""
from __future__ import annotations

import hashlib
import hmac
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

from . import bank, custom

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
MISTAKES_FILE = Path(__file__).resolve().parents[1] / "content" / "mistakes.yaml"
LABEL_MAX = 60

_CODE_RE = re.compile(rf"^[{CODE_ALPHABET}]{{{CODE_LEN}}}$")


class RoomError(bank.BankError):
    """An error with an explicit HTTP status; the message is Vietnamese and shown to the user."""

    def __init__(self, message: str, status: int):
        super().__init__(message)
        self.status = status


def _now() -> float:
    return time.time()


# --------------------------------------------------------------------------- labels


_notes: Optional[dict] = None


def _mistake_notes() -> dict:
    global _notes
    if _notes is None:
        try:
            _notes = yaml.safe_load(MISTAKES_FILE.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            _notes = {}
    return _notes


LABELS_FILE = MISTAKES_FILE.with_name("mistake_labels.yaml")
_labels: Optional[dict] = None


def _mistake_labels() -> dict:
    """Hand-written short labels for the projector (content/mistake_labels.yaml)."""
    global _labels
    if _labels is None:
        try:
            _labels = yaml.safe_load(LABELS_FILE.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            _labels = {}
    return _labels


def _short(text: str) -> str:
    text = text.strip()
    if ":" in text:
        text = text.split(":", 1)[0]
    else:
        text = re.split(r"(?<=[.!?])\s", text, maxsplit=1)[0]
    text = text.strip().rstrip(".!?").strip()
    return text if len(text) <= LABEL_MAX else text[:LABEL_MAX - 1].rstrip() + "…"


def mistake_label(key: Optional[str]) -> str:
    """Short Vietnamese label for a mistake key (a named mistake or an error group)."""
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
                f"Bạn đã mở {RATE_LIMIT} phòng học trong một giờ qua, đó là mức tối đa. Hãy thử lại sau.", 429)
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
    created_at REAL NOT NULL, last_activity REAL NOT NULL, open INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS players (
    id TEXT PRIMARY KEY, room TEXT NOT NULL, nickname TEXT NOT NULL, token_hash TEXT NOT NULL,
    joined_at REAL NOT NULL, last_seen REAL NOT NULL,
    score INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'playing',
    bugs_fixed INTEGER NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS idx_players_room ON players (room);
CREATE TABLE IF NOT EXISTS answers (
    id INTEGER PRIMARY KEY AUTOINCREMENT, room TEXT NOT NULL, player_id TEXT NOT NULL,
    puzzle_id TEXT NOT NULL, template_id TEXT NOT NULL, topic TEXT NOT NULL, type TEXT NOT NULL,
    correct INTEGER NOT NULL, mistake_key TEXT, ts REAL NOT NULL);
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
        raise RoomError("Không tìm thấy phòng học này.", 404)
    if row["last_activity"] < _now() - TTL_S:
        _wipe(con, code)
        con.commit()
        raise RoomError("Phòng học này đã hết hạn (12 giờ sau lần hoạt động cuối).", 404)
    return row


def _check_teacher(row: sqlite3.Row, teacher_key: Optional[str]) -> None:
    if not teacher_key or not hmac.compare_digest(_hash(teacher_key), row["teacher_hash"]):
        raise RoomError("Sai mã giáo viên.", 403)


def _clean_text(text: str, limit: int, what: str, *, required: bool) -> str:
    text = (text or "").strip()
    if any(unicodedata.category(ch).startswith("C") for ch in text):
        raise RoomError(f"{what} không được chứa ký tự điều khiển.", 422)
    if required and not text:
        raise RoomError(f"{what} không được để trống.", 422)
    if len(text) > limit:
        raise RoomError(f"{what} tối đa {limit} ký tự.", 422)
    return text


# --------------------------------------------------------------------------- public API


def create_room(level: str, title: Optional[str], client: Optional[str]) -> dict:
    title = _clean_text(title or "", MAX_TITLE, "Tên phòng", required=False)
    _take_slot(client_key(client))
    teacher_key = secrets.token_hex(16)
    now = _now()
    with closing(_connect()) as con, _db_lock:
        _purge(con)
        for _ in range(20):
            code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LEN))
            try:
                con.execute("INSERT INTO rooms VALUES (?,?,?,?,?,?,1)",
                            (code, _hash(teacher_key), level, title, now, now))
                break
            except sqlite3.IntegrityError:
                continue
        else:  # pragma: no cover
            raise RoomError("Không tạo được phòng học, hãy thử lại.", 503)
        con.commit()
    return {"code": code, "teacher_key": teacher_key, "level": level, "title": title}


def room_info(code: str) -> dict:
    with closing(_connect()) as con:
        row = _load_room(con, code)
        players = con.execute("SELECT COUNT(*) FROM players WHERE room = ?", (row["code"],)).fetchone()[0]
    return {"code": row["code"], "level": row["level"], "title": row["title"],
            "open": bool(row["open"]), "players": players}


def join_room(code: str, nickname: str) -> dict:
    nickname = _clean_text(nickname, MAX_NICKNAME, "Biệt danh", required=True)
    with closing(_connect()) as con, _db_lock:
        _purge(con)
        room = _load_room(con, code)
        if not room["open"]:
            raise RoomError("Phòng học này đã đóng.", 410)
        existing = [r["nickname"].casefold() for r in
                    con.execute("SELECT nickname FROM players WHERE room = ?", (room["code"],))]
        if len(existing) >= MAX_PLAYERS:
            raise RoomError(f"Phòng học đã đủ {MAX_PLAYERS} người.", 409)
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
                        "mistake_key, ts) VALUES (?,?,?,?,?,?,?,?,?)",
                        (code, player["id"], puzzle["id"], puzzle["template_id"], topic, ptype,
                         1 if result["correct"] else 0, mistake, now))
            con.execute("UPDATE players SET last_seen = ? WHERE id = ?", (now, player["id"]))
            con.execute("UPDATE rooms SET last_activity = ? WHERE code = ?", (now, code))
            con.commit()
    except Exception:  # noqa: BLE001 - deliberately broad, see docstring
        return


def record_progress(code: str, token: str, score: int, status: str, bugs_fixed: int) -> None:
    with closing(_connect()) as con, _db_lock:
        room = _load_room(con, code)
        player = _find_player(con, room["code"], token)
        if player is None:
            raise RoomError("Mã người chơi không hợp lệ.", 403)
        if not room["open"]:
            return  # a closed room keeps its final board
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
            prompt = bank.get_puzzle(pid)["prompt"]
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
        ({"nickname": p["nickname"], "score": p["score"], "status": p["status"],
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


def join_url(code: str, *, headers, scheme: str, netloc: str) -> str:
    """Absolute join link. ``SYNTAX_STACK_PUBLIC_URL`` wins; else the forwarded proto/host the reverse
    proxy sends, else the request's own."""
    base = os.getenv("SYNTAX_STACK_PUBLIC_URL", "").strip().rstrip("/")
    if not base:
        proto = (headers.get("x-forwarded-proto") or "").split(",")[0].strip().lower()
        if proto not in ("http", "https"):
            proto = scheme
        host = (headers.get("x-forwarded-host") or "").split(",")[0].strip()
        if not host or not _HOST_RE.match(host):
            host = headers.get("host") or netloc
        base = f"{proto}://{host}"
    return f"{base}/?room={code}"


def qr_svg(url: str) -> str:
    import io

    import segno
    buf = io.BytesIO()
    segno.make(url, error="m").save(buf, kind="svg", dark="#141518", light="#ffffff", border=2, scale=8,
                                    xmldecl=False, nl=False)
    return buf.getvalue().decode("utf-8")
