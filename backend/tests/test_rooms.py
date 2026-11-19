"""Live classroom rooms: create/join, server-verified answer logging, the teacher summary, and limits."""
import sqlite3

import pytest

from app import bank, rooms

CODE_CHARS = set("ABCDEFGHJKLMNPQRSTUVWXYZ23456789")


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(rooms, "DB_PATH", tmp_path / "rooms.sqlite")
    monkeypatch.setattr(rooms, "_db_path_cache", None)
    monkeypatch.delenv("SYNTAX_STACK_PUBLIC_URL", raising=False)
    rooms.reset_rate_limits()
    yield
    rooms.reset_rate_limits()


# --------------------------------------------------------------------------- helpers


def make_room(client, **extra):
    extra.setdefault("names", "free")   # most tests choose their own nicknames; random mode has its own tests
    r = client.post("/api/rooms", json={"level": "intermediate", "title": "Lớp 10A", **extra})
    assert r.status_code == 200, r.text
    return r.json()


def join(client, code, nickname="An"):
    r = client.post(f"/api/rooms/{code}/join", json={"nickname": nickname})
    assert r.status_code == 200, r.text
    return r.json()


def summary(client, room, expect=200):
    r = client.get(f"/api/rooms/{room['code']}/summary", headers={"X-Teacher-Key": room["teacher_key"]})
    assert r.status_code == expect, r.text
    return r.json()


def answer(client, puzzle_id, body, room=None, token=None):
    payload = dict(body)
    if room is not None:
        payload["room"] = room["code"] if isinstance(room, dict) else room
    if token is not None:
        payload["player_token"] = token
    return client.post(f"/api/puzzle/{puzzle_id}/answer", json=payload)


def of_type(all_rows, typ, topic=None):
    return [r for r in all_rows if r["type"] == typ and not r["debug_only"] and (topic is None or r["topic"] == topic)]


def correct_body(row):
    d = row["data"]
    if row["type"] == "parsons":
        return {"order": [{"line_id": s["line_id"], "indent": s["indent"]} for s in d["solution"]]}
    return {"option_id": next(o["id"] for o in d["options"] if o["correct"])}


def wrong_option(row, named=None):
    for o in row["data"]["options"]:
        if not o["correct"] and (named is None or bool(o.get("name")) == named):
            return o
    return None


def wrong_body(row, **kw):
    if row["type"] == "parsons":
        return {"order": [{"line_id": l["id"], "indent": 0} for l in row["data"]["lines"]]}
    return {"option_id": wrong_option(row, **kw)["id"]}


def named_fill(all_rows, topic=None):
    """A fill_blank whose first wrong option has a named mistake that has a note in mistakes.yaml."""
    notes = rooms._mistake_notes()
    for r in of_type(all_rows, "fill_blank", topic):
        o = wrong_option(r, named=True)
        if o and o["name"] in notes and ":" in notes[o["name"]]:
            return r, o
    raise AssertionError("no named fill_blank puzzle with a colon note")


def wrong_parsons(all_rows):
    for r in of_type(all_rows, "parsons"):
        body = wrong_body(r)
        if not answer_is_correct(r, body):
            return r, body
    raise AssertionError("no parsons puzzle with a wrong all-indent-0 order")


def answer_is_correct(row, body):
    return bank.check_answer(row, option_id=body.get("option_id"), order=body.get("order"))["correct"]


# --------------------------------------------------------------------------- create / join


def test_create_room_shape(client):
    room = make_room(client)
    assert set(room) == {"code", "teacher_key", "join_url", "level", "title", "names"}
    assert len(room["code"]) == 5 and set(room["code"]) <= CODE_CHARS
    assert len(room["teacher_key"]) == 32 and int(room["teacher_key"], 16) >= 0
    assert room["join_url"] == f"http://testserver/?room={room['code']}"
    assert room["level"] == "intermediate" and room["title"] == "Lớp 10A"


def test_create_room_validation(client):
    assert client.post("/api/rooms", json={"level": "expert"}).status_code == 422
    assert client.post("/api/rooms", json={"level": "beginner", "title": "x" * 41}).status_code == 422
    assert client.post("/api/rooms", json={"level": "beginner", "title": "bad\x07title"}).status_code == 422
    ok = client.post("/api/rooms", json={"level": "beginner"})
    assert ok.status_code == 200 and ok.json()["title"] == ""


def test_get_room_case_insensitive_and_unknown(client):
    room = make_room(client)
    join(client, room["code"], "An")
    r = client.get(f"/api/rooms/{room['code'].lower()}")
    assert r.status_code == 200
    assert r.json() == {"code": room["code"], "level": "intermediate", "title": "Lớp 10A",
                        "open": True, "players": 1, "names": "free"}
    assert client.get("/api/rooms/ZZZZZ").status_code == 404
    assert client.get("/api/rooms/abc").status_code == 404


def test_join_returns_credentials_and_uppercases_code(client):
    room = make_room(client)
    p = join(client, room["code"].lower(), "  Minh  ")
    assert set(p) == {"player_id", "player_token", "nickname", "level"}
    assert p["nickname"] == "Minh" and p["level"] == "intermediate"
    assert len(p["player_token"]) == 32
    assert client.post("/api/rooms/ZZZZZ/join", json={"nickname": "An"}).status_code == 404


def test_duplicate_nicknames_get_a_suffix(client):
    room = make_room(client)
    names = [join(client, room["code"], n)["nickname"] for n in ("An", "an", "AN", "Binh")]
    assert names == ["An", "an 2", "AN 3", "Binh"]


@pytest.mark.parametrize("nick", ["", "   ", "x" * 21, "a\nb", "tab\there", "nul\x00", "zero​width"])
def test_nickname_validation(client, nick):
    room = make_room(client)
    r = client.post(f"/api/rooms/{room['code']}/join", json={"nickname": nick})
    assert r.status_code == 422
    assert client.get(f"/api/rooms/{room['code']}").json()["players"] == 0


def test_nickname_unicode_and_limit_ok(client):
    room = make_room(client)
    assert join(client, room["code"], "Nguyễn Văn Ă")["nickname"] == "Nguyễn Văn Ă"
    assert join(client, room["code"], "y" * 20)["nickname"] == "y" * 20


def test_player_cap_is_409(client):
    room = make_room(client)
    for i in range(rooms.MAX_PLAYERS):
        join(client, room["code"], f"hs{i}")
    r = client.post(f"/api/rooms/{room['code']}/join", json={"nickname": "late"})
    assert r.status_code == 409
    assert client.get(f"/api/rooms/{room['code']}").json()["players"] == rooms.MAX_PLAYERS


def test_closed_room_is_410(client):
    room = make_room(client)
    join(client, room["code"])
    r = client.post(f"/api/rooms/{room['code']}/close", headers={"X-Teacher-Key": room["teacher_key"]})
    assert r.status_code == 200 and r.json() == {"open": False}
    assert client.post(f"/api/rooms/{room['code']}/join", json={"nickname": "Late"}).status_code == 410
    assert client.get(f"/api/rooms/{room['code']}").json()["open"] is False
    assert summary(client, room)["open"] is False


# --------------------------------------------------------------------------- answers are server-verified


def test_happy_path_grid_mistakes_unsolved_recent(client, all_rows):
    room = make_room(client)
    a = join(client, room["code"], "An")
    b = join(client, room["code"], "Binh")

    fill, named = named_fill(all_rows)
    expected_label = rooms.mistake_label(named["name"])  # hand-written label from mistake_labels.yaml
    fill_ok = answer(client, fill["id"], correct_body(fill), room, a["player_token"]).json()
    assert fill_ok["correct"] is True
    for tok in (a["player_token"], b["player_token"]):
        assert answer(client, fill["id"], {"option_id": named["id"]}, room, tok).json()["correct"] is False

    pred = of_type(all_rows, "predict_output")[0]
    for _ in range(2):  # two wrong attempts, never solved: an "unsolved" puzzle
        answer(client, pred["id"], wrong_body(pred), room, b["player_token"])

    pars, pbody = wrong_parsons(all_rows)
    assert answer(client, pars["id"], pbody, room, a["player_token"]).json()["correct"] is False

    s = summary(client, room)
    assert set(s) == {"code", "title", "level", "open", "created_at", "totals", "players", "grid",
                      "top_mistakes", "unsolved", "recent"}
    assert s["totals"] == {"players": 2, "answers": 6, "correct": 1}

    # grid: 4 topics x 4 types, zero-filled, counts land in the right cell
    assert set(s["grid"]) == set(rooms.TOPICS)
    assert all(set(cells) == set(rooms.TYPES) for cells in s["grid"].values())
    assert s["grid"][fill["topic"]]["fill_blank"] == {"answers": 3, "correct": 1}
    assert s["grid"][pred["topic"]]["predict_output"]["answers"] == 2
    assert s["grid"][pars["topic"]]["parsons"] == {"answers": 1, "correct": 0}
    assert sum(c["answers"] for t in s["grid"].values() for c in t.values()) == 6

    # top mistakes: the named mistake leads, with a Vietnamese label and distinct players
    top = s["top_mistakes"][0]
    assert top == {"key": named["name"], "label": expected_label, "count": 2, "topic": fill["topic"],
                   "players": 2}
    assert len(expected_label) <= 60
    assert len(s["top_mistakes"]) <= 5

    # unsolved: only the predict puzzle (2 wrong, 0 correct); the fill was solved, parsons has 1 wrong
    assert [u["puzzle_id"] for u in s["unsolved"]] == [pred["id"]]
    u = s["unsolved"][0]
    assert u["prompt"] == pred["prompt"] and u["attempts"] == 2 and u["players"] == 1
    assert u["topic"] == pred["topic"]

    # players and recent
    assert {p["nickname"]: (p["answers"], p["correct"]) for p in s["players"]} == {"An": (3, 1), "Binh": (3, 0)}
    assert all(p["score"] == 0 and p["status"] == "playing" and p["last_seen_s"] >= 0 for p in s["players"])
    assert len(s["recent"]) == 6
    newest = s["recent"][0]
    assert newest["nickname"] == "An" and newest["type"] == "parsons" and newest["correct"] is False
    assert newest["mistake_label"] and newest["ago_s"] >= 0
    oldest = s["recent"][-1]
    assert oldest["correct"] is True and oldest["mistake_label"] is None


def test_group_labels_and_parsons_use_error_group(client, all_rows):
    room = make_room(client)
    p = join(client, room["code"])
    pars, body = wrong_parsons(all_rows)
    group = bank.check_answer(pars, order=body["order"])["error_group"]
    answer(client, pars["id"], body, room, p["player_token"])
    top = summary(client, room)["top_mistakes"][0]
    assert top["key"] == group
    assert top["label"] == rooms.GROUP_LABELS.get(group, "Lỗi khác")


def test_label_rules():
    assert rooms.mistake_label("output_mismatch") == "Sai kết quả đầu ra"
    assert rooms.mistake_label("wrong_order") == "Sai thứ tự"
    assert rooms.mistake_label("bad_indent") == "Sai thụt lề"
    assert rooms.mistake_label("syntax") == "Lỗi cú pháp"
    assert rooms.mistake_label("wrong_fix") == "Sửa sai dòng"
    assert rooms.mistake_label("wrong_line") == "Sửa nhầm dòng"
    assert rooms.mistake_label("runtime") == "Lỗi khi chạy"
    assert rooms.mistake_label("other") == "Lỗi khác"
    assert rooms.mistake_label("never_heard_of_it") == "Lỗi khác"
    assert rooms.mistake_label(None) == "Lỗi khác"
    # hand-written short labels win over notes
    assert rooms.mistake_label("off_by_one_high") == "Lệch một đơn vị (thừa)"
    assert rooms.mistake_label("range_includes_end") == "Tưởng range() gồm số cuối"
    # a note-only key (no hand-written label) still uses the colon / first-sentence rule
    rooms._mistake_labels()  # load
    saved = rooms._labels.pop("range_includes_end")
    try:
        assert rooms.mistake_label("range_includes_end") == rooms._short(rooms._mistake_notes()["range_includes_end"])
    finally:
        rooms._labels["range_includes_end"] = saved
    for key in rooms._mistake_notes():
        assert 0 < len(rooms.mistake_label(key)) <= 60


def test_clients_cannot_fake_results(client, all_rows):
    """Correctness comes from the bank. Progress and join never touch the answer log."""
    room = make_room(client)
    p = join(client, room["code"])
    client.post(f"/api/rooms/{room['code']}/progress",
                json={"player_token": p["player_token"], "score": 9999, "status": "playing", "bugs_fixed": 50})
    fill, named = named_fill(all_rows)
    # a wrong choice is logged as wrong whatever else the body claims
    r = client.post(f"/api/puzzle/{fill['id']}/answer", json={
        "option_id": named["id"], "room": room["code"], "player_token": p["player_token"],
        "correct": True, "mistake_key": "nothing", "topic": "loops"})
    assert r.json()["correct"] is False
    s = summary(client, room)
    assert s["totals"] == {"players": 1, "answers": 1, "correct": 0}
    assert s["top_mistakes"][0]["key"] == named["name"]
    # the reported 9999 is capped at the empty-board ceiling (nothing was verified); answers are never client data
    assert s["players"][0]["score"] == rooms.score_ceiling({}) and s["players"][0]["answers"] == 1


def test_invalid_room_or_token_is_ignored_without_breaking_answer(client, all_rows):
    room = make_room(client)
    p = join(client, room["code"])
    fill = of_type(all_rows, "fill_blank")[0]
    body = correct_body(fill)
    plain = answer(client, fill["id"], body).json()
    for r_code, tok in [("ZZZZZ", p["player_token"]), (room["code"], "0" * 32), ("not a code!", "x"),
                        (room["code"], None), (None, p["player_token"])]:
        payload = dict(body, **({"room": r_code} if r_code else {}), **({"player_token": tok} if tok else {}))
        r = client.post(f"/api/puzzle/{fill['id']}/answer", json=payload)
        assert r.status_code == 200 and r.json() == plain
    assert summary(client, room)["totals"]["answers"] == 0
    # and a valid pair logs
    answer(client, fill["id"], body, room, p["player_token"])
    assert summary(client, room)["totals"]["answers"] == 1


def test_token_from_another_room_is_ignored(client, all_rows):
    r1, r2 = make_room(client), make_room(client)
    p1 = join(client, r1["code"])
    fill = of_type(all_rows, "fill_blank")[0]
    answer(client, fill["id"], correct_body(fill), r2, p1["player_token"])
    assert summary(client, r2)["totals"]["answers"] == 0
    assert summary(client, r1)["totals"]["answers"] == 0


def test_logging_failure_never_breaks_the_answer(client, all_rows, monkeypatch):
    room = make_room(client)
    p = join(client, room["code"])

    def boom():
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(rooms, "_connect", boom)
    fill = of_type(all_rows, "fill_blank")[0]
    r = answer(client, fill["id"], correct_body(fill), room, p["player_token"])
    assert r.status_code == 200 and r.json()["correct"] is True


def test_malformed_answer_is_not_logged(client, all_rows):
    room = make_room(client)
    p = join(client, room["code"])
    fill = of_type(all_rows, "fill_blank")[0]
    r = answer(client, fill["id"], {"option_id": "zzz"}, room, p["player_token"])
    assert r.status_code == 422
    assert summary(client, room)["totals"]["answers"] == 0


def test_closed_room_stops_logging(client, all_rows):
    room = make_room(client)
    p = join(client, room["code"])
    fill = of_type(all_rows, "fill_blank")[0]
    client.post(f"/api/rooms/{room['code']}/close", headers={"X-Teacher-Key": room["teacher_key"]})
    r = answer(client, fill["id"], correct_body(fill), room, p["player_token"])
    assert r.status_code == 200
    assert summary(client, room)["totals"]["answers"] == 0


def test_custom_puzzle_ids_are_not_logged(client, monkeypatch):
    room = make_room(client)
    p = join(client, room["code"])
    called = []
    monkeypatch.setattr(rooms, "log_answer", lambda *a, **k: called.append(a))
    client.post("/api/puzzle/c-abcdefgh-1/answer",
                json={"option_id": "a", "room": room["code"], "player_token": p["player_token"]})
    assert called == []


def test_all_four_types_land_in_their_grid_column(client, all_rows):
    room = make_room(client)
    p = join(client, room["code"])
    for typ in rooms.TYPES:
        row = of_type(all_rows, typ)[0]
        assert row["template_id"].rsplit("_", 1)[-1] == {"fill_blank": "fill", "predict_output": "predict",
                                                         "parsons": "parsons", "find_bug": "bug"}[typ]
        answer(client, row["id"], correct_body(row), room, p["player_token"])
    s = summary(client, room)
    for typ in rooms.TYPES:
        assert sum(t[typ]["answers"] for t in s["grid"].values()) == 1
    assert s["totals"] == {"players": 1, "answers": 4, "correct": 4}


def test_per_player_answer_cap(client, all_rows, monkeypatch):
    monkeypatch.setattr(rooms, "MAX_ANSWERS_PER_PLAYER", 3)
    room = make_room(client)
    p = join(client, room["code"])
    fill = of_type(all_rows, "fill_blank")[0]
    for _ in range(6):
        assert answer(client, fill["id"], correct_body(fill), room, p["player_token"]).status_code == 200
    assert summary(client, room)["totals"]["answers"] == 3


# --------------------------------------------------------------------------- progress / leaderboard


def post_progress(client, room, player, score, status="playing", bugs_fixed=0):
    return client.post(f"/api/rooms/{room['code']}/progress", json={
        "player_token": player["player_token"], "score": score, "status": status, "bugs_fixed": bugs_fixed})


def solve(client, all_rows, room, player, n, tier=None, skip=0):
    """``n`` distinct correct answers (the server logs them); returns the puzzle rows used."""
    pool = [r for r in all_rows if not r["debug_only"] and (tier is None or r["tier"] == tier)][skip:skip + n]
    assert len(pool) == n
    for r in pool:
        assert answer(client, r["id"], correct_body(r), room, player["player_token"]).json()["correct"] is True
    return pool


def stored(player):
    """(score, bugs_fixed) as stored (the summary has no bugs_fixed)."""
    con = rooms._connect()
    try:
        r = con.execute("SELECT score, bugs_fixed FROM players WHERE id = ?", (player["player_id"],)).fetchone()
    finally:
        con.close()
    return r["score"], r["bugs_fixed"]


def test_progress_updates_leaderboard_sorted_by_score(client, all_rows):
    room = make_room(client)
    a, b, c = (join(client, room["code"], n) for n in ("An", "Binh", "Chi"))
    for p in (a, b, c):
        solve(client, all_rows, room, p, 3, tier=1)         # three verified answers: ceiling 64 + 3 * 217 = 715
    for p, score, status in ((a, 120, "playing"), (b, 700, "crash"), (c, 400, "nofit")):
        r = post_progress(client, room, p, score, status, 2)
        assert r.status_code == 204 and r.content == b""
    board = summary(client, room)["players"]
    assert [(p["nickname"], p["score"], p["status"]) for p in board] == [
        ("Binh", 700, "crash"), ("Chi", 400, "nofit"), ("An", 120, "playing")]


def test_progress_is_capped_at_the_ceiling_of_the_verified_answers(client, all_rows):
    room = make_room(client)
    p = join(client, room["code"])
    assert post_progress(client, room, p, 99999).status_code == 204     # nothing verified yet: one empty board
    assert stored(p)[0] == 64 == rooms.score_ceiling({})
    used = solve(client, all_rows, room, p, 2, tier=1) + solve(client, all_rows, room, p, 1, tier=3, skip=3)
    ceiling = 64 + 2 * 217 + 927
    assert rooms.score_ceiling(rooms.counted_correct([(r["id"], 1, r["tier"]) for r in used])) == ceiling
    assert post_progress(client, room, p, 99999).status_code == 204
    assert summary(client, room)["players"][0]["score"] == ceiling
    assert post_progress(client, room, p, ceiling + 1).status_code == 204
    assert stored(p)[0] == ceiling


def test_an_honest_score_is_stored_unchanged(client, all_rows):
    room = make_room(client)
    p = join(client, room["code"])
    solve(client, all_rows, room, p, 5, tier=1)
    for score in (0, 1, 64, 300, 1149):                 # 64 + 5 * 217 = 1149 is the ceiling itself
        assert post_progress(client, room, p, score).status_code == 204
        assert summary(client, room)["players"][0]["score"] == score


def test_wrong_and_repeated_answers_do_not_raise_the_ceiling(client, all_rows):
    room = make_room(client)
    p = join(client, room["code"])
    fill = of_type(all_rows, "fill_blank")[0]
    for _ in range(4):                                  # the same puzzle answered correctly again and again
        assert answer(client, fill["id"], correct_body(fill), room, p["player_token"]).json()["correct"]
    pred = of_type(all_rows, "predict_output")[0]
    for _ in range(5):                                  # wrong answers earn nothing
        answer(client, pred["id"], wrong_body(pred), room, p["player_token"])
    post_progress(client, room, p, 10**6)
    assert stored(p)[0] == rooms.score_ceiling({fill["tier"]: 1})


def test_bugs_fixed_is_capped_by_the_verified_correct_answers(client, all_rows):
    room = make_room(client)
    p = join(client, room["code"])
    post_progress(client, room, p, 50, bugs_fixed=40)
    assert stored(p) == (50, 0)
    solve(client, all_rows, room, p, 2)
    post_progress(client, room, p, 50, bugs_fixed=40)
    assert stored(p) == (50, 2)
    post_progress(client, room, p, 50, bugs_fixed=1)
    assert stored(p) == (50, 1)


def test_record_progress_clamps_negative_values(client):
    room = make_room(client)
    p = join(client, room["code"])
    rooms.record_progress(room["code"], p["player_token"], -5, "playing", -3)
    assert stored(p) == (0, 0)


def test_the_ceiling_is_per_player(client, all_rows):
    room = make_room(client)
    a, b = join(client, room["code"], "An"), join(client, room["code"], "Binh")
    solve(client, all_rows, room, a, 4, tier=3)
    post_progress(client, room, b, 99999)                # Binh verified nothing, whatever An did
    post_progress(client, room, a, 99999)
    assert stored(b)[0] == 64
    assert stored(a)[0] == 64 + 4 * 927


def test_answers_logged_before_tiers_were_stored_count_as_tier_3(client, tmp_path, monkeypatch):
    old = tmp_path / "old-rooms.sqlite"
    con = sqlite3.connect(old)
    con.executescript(rooms._SCHEMA.replace(", tier INTEGER", ""))     # the answers table as it was before
    con.close()
    monkeypatch.setattr(rooms, "DB_PATH", old)
    room = make_room(client)
    p = join(client, room["code"])
    con = rooms._connect()                                # the migration adds the column
    try:
        assert "tier" in [r["name"] for r in con.execute("PRAGMA table_info(answers)")]
        con.execute("INSERT INTO answers (room, player_id, puzzle_id, template_id, topic, type, correct, ts) "
                    "VALUES (?,?,?,?,?,?,1,0)", (room["code"], p["player_id"], "x", "t", "loops", "fill_blank"))
        con.commit()
    finally:
        con.close()
    post_progress(client, room, p, 10**6)
    assert stored(p)[0] == 64 + 927


@pytest.mark.parametrize("bad", [
    {"score": -1}, {"score": 10**7 + 1}, {"status": "won"}, {"bugs_fixed": "many"}, {"score": 1.5}])
def test_progress_validation(client, bad):
    room = make_room(client)
    p = join(client, room["code"])
    body = {"player_token": p["player_token"], "score": 5, "status": "playing", "bugs_fixed": 0, **bad}
    assert client.post(f"/api/rooms/{room['code']}/progress", json=body).status_code == 422


def test_progress_bad_token_is_403(client):
    room = make_room(client)
    r = client.post(f"/api/rooms/{room['code']}/progress",
                    json={"player_token": "0" * 32, "score": 5, "status": "playing", "bugs_fixed": 0})
    assert r.status_code == 403


# --------------------------------------------------------------------------- teacher key, delete, expiry


def test_teacher_key_required(client):
    room = make_room(client)
    code = room["code"]
    for headers in ({}, {"X-Teacher-Key": "0" * 32}, {"X-Teacher-Key": room["teacher_key"][:-1]}):
        assert client.get(f"/api/rooms/{code}/summary", headers=headers).status_code == 403
        assert client.post(f"/api/rooms/{code}/close", headers=headers).status_code == 403
        assert client.delete(f"/api/rooms/{code}", headers=headers).status_code == 403
    assert client.get("/api/rooms/ZZZZZ/summary", headers={"X-Teacher-Key": "x"}).status_code == 404
    assert client.get(f"/api/rooms/{code}").json()["open"] is True  # the failed attempts changed nothing
    # the public room payload never exposes the key
    assert room["teacher_key"] not in client.get(f"/api/rooms/{code}").text


def test_delete_wipes_everything(client, all_rows, tmp_path):
    room = make_room(client)
    p = join(client, room["code"])
    fill = of_type(all_rows, "fill_blank")[0]
    answer(client, fill["id"], correct_body(fill), room, p["player_token"])
    r = client.delete(f"/api/rooms/{room['code']}", headers={"X-Teacher-Key": room["teacher_key"]})
    assert r.status_code == 204 and r.content == b""
    assert client.get(f"/api/rooms/{room['code']}").status_code == 404
    assert client.get(f"/api/rooms/{room['code']}/summary",
                      headers={"X-Teacher-Key": room["teacher_key"]}).status_code == 404
    con = sqlite3.connect(rooms.DB_PATH)
    try:
        for table in ("rooms", "players", "answers"):
            assert con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
    finally:
        con.close()


def test_expired_room_is_gone_and_purged(client, all_rows, monkeypatch):
    old = make_room(client)
    p = join(client, old["code"])
    fill = of_type(all_rows, "fill_blank")[0]
    answer(client, fill["id"], correct_body(fill), old, p["player_token"])
    real = rooms._now
    monkeypatch.setattr(rooms, "_now", lambda: real() + rooms.TTL_S + 60)
    assert client.get(f"/api/rooms/{old['code']}").status_code == 404
    assert client.post(f"/api/rooms/{old['code']}/join", json={"nickname": "x"}).status_code == 404
    con = sqlite3.connect(rooms.DB_PATH)
    try:
        for table in ("rooms", "players", "answers"):
            assert con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
    finally:
        con.close()


def test_lazy_purge_on_create_and_activity_extends_life(client, all_rows, monkeypatch):
    stale = make_room(client)
    active = make_room(client)
    pa = join(client, active["code"])
    real = rooms._now
    t = [real()]
    monkeypatch.setattr(rooms, "_now", lambda: t[0])
    t[0] += rooms.TTL_S - 600
    fill = of_type(all_rows, "fill_blank")[0]
    answer(client, fill["id"], correct_body(fill), active, pa["player_token"])  # activity renews the 12 h
    t[0] += 3600
    assert client.get(f"/api/rooms/{active['code']}").status_code == 200
    make_room(client)  # create purges expired rooms, including the stale one
    con = sqlite3.connect(rooms.DB_PATH)
    try:
        left = {r[0] for r in con.execute("SELECT code FROM rooms")}
    finally:
        con.close()
    assert stale["code"] not in left and active["code"] in left


# --------------------------------------------------------------------------- rate limit, join_url, QR


def test_rate_limit_five_rooms_per_hour_per_ip(client):
    for _ in range(5):
        assert client.post("/api/rooms", json={"level": "beginner"}).status_code == 200
    r = client.post("/api/rooms", json={"level": "beginner"})
    assert r.status_code == 429 and "detail" in r.json()
    other = client.post("/api/rooms", json={"level": "beginner"}, headers={"CF-Connecting-IP": "203.0.113.9"})
    assert other.status_code == 200  # another visitor is not limited


def test_rate_limit_window_expires(client, monkeypatch):
    for _ in range(5):
        client.post("/api/rooms", json={"level": "beginner"})
    assert client.post("/api/rooms", json={"level": "beginner"}).status_code == 429
    real = rooms._now
    monkeypatch.setattr(rooms, "_now", lambda: real() + rooms.RATE_WINDOW_S + 5)
    assert client.post("/api/rooms", json={"level": "beginner"}).status_code == 200


def test_join_url_honours_forwarded_headers(client):
    r = client.post("/api/rooms", json={"level": "beginner"},
                    headers={"X-Forwarded-Proto": "https", "X-Forwarded-Host": "stack.example.vn"})
    assert r.json()["join_url"] == f"https://stack.example.vn/?room={r.json()['code']}"
    # first value of a proxy chain; hostile host values are ignored
    r = client.post("/api/rooms", json={"level": "beginner"},
                    headers={"X-Forwarded-Proto": "https, http", "X-Forwarded-Host": "a.example.vn, b"})
    assert r.json()["join_url"].startswith("https://a.example.vn/?room=")
    r = client.post("/api/rooms", json={"level": "beginner"},
                    headers={"X-Forwarded-Proto": "javascript", "X-Forwarded-Host": "evil.com/x?y"})
    assert r.json()["join_url"].startswith("http://testserver/?room=")


def test_join_url_env_override(client, monkeypatch):
    monkeypatch.setenv("SYNTAX_STACK_PUBLIC_URL", "https://syntaxstack.example/")
    r = client.post("/api/rooms", json={"level": "beginner"},
                    headers={"X-Forwarded-Proto": "http", "X-Forwarded-Host": "ignored.example"})
    assert r.json()["join_url"] == f"https://syntaxstack.example/?room={r.json()['code']}"


def test_qr_svg(client, monkeypatch):
    room = make_room(client)
    r = client.get(f"/api/rooms/{room['code'].lower()}/qr.svg")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/svg+xml")
    assert "max-age" in r.headers["cache-control"]
    svg = r.text
    assert "<svg" in svg and "#141518" in svg and "<?xml" not in svg
    assert "#fff" in svg.lower()  # dark modules on a white field: phone cameras need dark-on-light to scan
    assert client.get("/api/rooms/ZZZZZ/qr.svg").status_code == 404
    # the QR encodes the same join_url the room reports (env override flows through)
    monkeypatch.setenv("SYNTAX_STACK_PUBLIC_URL", "https://syntaxstack.example")
    assert client.get(f"/api/rooms/{room['code']}/qr.svg").text != svg


def test_security_headers_and_no_store_on_room_api(client):
    room = make_room(client)
    r = client.get(f"/api/rooms/{room['code']}")
    assert r.headers["cache-control"] == "no-store"


def test_every_template_mistake_has_a_short_dashboard_label():
    """The projector's "Lỗi phổ biến nhất" card must never fall back to "Lỗi khác" for a named mistake."""
    import glob
    import yaml
    labels = yaml.safe_load(rooms.LABELS_FILE.read_text(encoding="utf-8"))
    names = set()
    for f in glob.glob(str(rooms.MISTAKES_FILE.parent / "templates" / "*.yaml")):
        tpl = yaml.safe_load(open(f, encoding="utf-8"))
        for tier in tpl["tiers"].values():
            for block in tier:
                for d in block.get("distractors", []):
                    if isinstance(d, dict) and d.get("name"):
                        names.add(d["name"])
    missing = sorted(n for n in names if not (isinstance(labels.get(n), str) and labels[n].strip()))
    assert not missing, missing
    too_long = sorted(n for n, v in labels.items() if len(v) > 34)
    assert not too_long, too_long
    assert rooms.mistake_label("repeated_one_less") == "Lặp thiếu một lần"



# --------------------------------------------------------------------------- generated names and moderation


def test_random_mode_is_the_default_and_ignores_a_supplied_nickname(client):
    from app import nicknames
    room = client.post("/api/rooms", json={"level": "beginner"}).json()
    assert room["names"] == "random"
    assert client.get(f"/api/rooms/{room['code']}").json()["names"] == "random"
    a = client.post(f"/api/rooms/{room['code']}/join", json={"nickname": "Fuck You"}).json()
    b = client.post(f"/api/rooms/{room['code']}/join", json={}).json()      # nickname is optional
    assert nicknames.is_generated(a["nickname"]) and nicknames.is_generated(b["nickname"])
    assert "fuck" not in a["nickname"].lower()
    assert a["nickname"] != b["nickname"]


def test_random_names_are_unique_within_a_room(client):
    room = client.post("/api/rooms", json={"level": "beginner"}).json()
    got = [client.post(f"/api/rooms/{room['code']}/join", json={}).json()["nickname"] for _ in range(rooms.MAX_PLAYERS)]
    assert len({n.casefold() for n in got}) == rooms.MAX_PLAYERS


def test_random_name_redraws_on_collision(client, monkeypatch):
    room = client.post("/api/rooms", json={"level": "beginner"}).json()
    seq = iter(["Mèo Xanh 42", "Mèo Xanh 42", "mèo xanh 42", "Cáo Vui 10"])
    monkeypatch.setattr(rooms.nicknames, "generate", lambda rng=None: next(seq))
    assert client.post(f"/api/rooms/{room['code']}/join", json={}).json()["nickname"] == "Mèo Xanh 42"
    assert client.post(f"/api/rooms/{room['code']}/join", json={}).json()["nickname"] == "Cáo Vui 10"


def test_invalid_names_mode_is_422(client):
    assert client.post("/api/rooms", json={"names": "both"}).status_code == 422


@pytest.mark.parametrize("bad", ["Fuuuck", "đ1t", "D.M", "v c l", "Mèo Lớn"])
def test_free_mode_rejects_blocked_names(client, bad):
    room = make_room(client, names="free")
    r = client.post(f"/api/rooms/{room['code']}/join", json={"nickname": bad})
    assert r.status_code == 422 and r.json()["detail"] == "Biệt danh này không được dùng. Hãy chọn tên khác."
    assert summary(client, room)["totals"]["players"] == 0


def test_free_mode_accepts_innocent_names_and_still_validates(client):
    room = make_room(client, names="free")
    for ok in ("Nguyễn An", "Clara", "Adam"):
        assert join(client, room["code"], ok)["nickname"] == ok
    assert client.post(f"/api/rooms/{room['code']}/join", json={}).status_code == 422
    assert client.post(f"/api/rooms/{room['code']}/join", json={"nickname": "x" * 21}).status_code == 422


def test_summary_players_carry_player_id(client):
    room = make_room(client)
    a = join(client, room["code"], "An")
    assert summary(client, room)["players"][0]["player_id"] == a["player_id"]


def test_kick_removes_the_player_everywhere_and_kills_the_token(client, all_rows):
    room = make_room(client)
    a, b = join(client, room["code"], "An"), join(client, room["code"], "Bình")
    fill = of_type(all_rows, "fill_blank")[0]
    wrong = next(o for o in fill["data"]["options"] if not o["correct"])
    for who in (a, b):
        answer(client, fill["id"], {"option_id": wrong["id"]}, room, who["player_token"])
    answer(client, fill["id"], {"option_id": wrong["id"]}, room, a["player_token"])
    s = summary(client, room)
    assert s["totals"]["players"] == 2 and s["totals"]["answers"] == 3 and len(s["unsolved"]) == 1

    url = f"/api/rooms/{room['code']}/players/{a['player_id']}/kick"
    assert client.post(url, headers={"X-Teacher-Key": "wrong"}).status_code == 403
    assert client.post(url).status_code == 403
    assert client.post(f"/api/rooms/{room['code']}/players/pnope/kick",
                       headers={"X-Teacher-Key": room["teacher_key"]}).status_code == 404
    assert client.post(url, headers={"X-Teacher-Key": room["teacher_key"]}).status_code == 204

    s = summary(client, room)
    assert [p["nickname"] for p in s["players"]] == ["Bình"]
    assert s["totals"] == {"players": 1, "answers": 1, "correct": 0}
    assert all(r["nickname"] == "Bình" for r in s["recent"]) and len(s["recent"]) == 1
    assert sum(c["answers"] for t in s["grid"].values() for c in t.values()) == 1
    assert sum(m["count"] for m in s["top_mistakes"]) == 1 and s["unsolved"] == []

    # the kicked token is dead: nothing is logged and progress is refused
    answer(client, fill["id"], {"option_id": wrong["id"]}, room, a["player_token"])
    assert summary(client, room)["totals"]["answers"] == 1
    r = client.post(f"/api/rooms/{room['code']}/progress",
                    json={"player_token": a["player_token"], "score": 5, "status": "playing", "bugs_fixed": 0})
    assert r.status_code == 403
    # a second kick is a 404, and rejoining as a new player works
    assert client.post(url, headers={"X-Teacher-Key": room["teacher_key"]}).status_code == 404
    again = join(client, room["code"], "An")
    assert again["player_id"] != a["player_id"] and summary(client, room)["totals"]["players"] == 2
