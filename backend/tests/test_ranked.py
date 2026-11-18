"""Ranked runs, the leaderboard and races (docs/ranked-and-race.md) through the real HTTP API."""
import secrets
import time
from contextlib import closing
from datetime import datetime

import pytest

from app import bank, ranked

from .ranked_bot import ApiSource, Bot

CODE_CHARS = set("ABCDEFGHJKLMNPQRSTUVWXYZ23456789")


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(ranked, "DB_PATH", tmp_path / "ranked.sqlite")
    monkeypatch.setattr(ranked, "_db_path_cache", None)
    monkeypatch.delenv("SYNTAX_STACK_PUBLIC_URL", raising=False)
    ranked.reset_rate_limits()
    yield
    ranked.reset_rate_limits()


def device():
    return secrets.token_hex(16)


GEN = "Mèo Xanh 42"   # a generated-format nickname; runs and races accept nothing else


def start(client, kind="ranked", level="beginner", nickname=GEN, dev=None, race=None, expect=200):
    body = {"kind": kind, "nickname": nickname, "device_id": dev or device()}
    if level:
        body["level"] = level
    if race:
        body["race"] = race
    r = client.post("/api/runs", json=body)
    assert r.status_code == expect, r.text
    return r.json()


def play_and_finish(client, run, wrong=(), hint_level=0, max_moves=60, expect=200, tamper=None):
    bot = Bot(run["seed"], run["level"], ApiSource(client, run, hint_level), wrong=wrong)
    moves = bot.play(max_moves)
    if tamper:
        moves = tamper(moves)
    r = client.post(f"/api/runs/{run['run_id']}/finish",
                    json={"run_token": run["run_token"], "moves": moves, "client_score": 123})
    assert r.status_code == expect, r.text
    return bot, moves, r.json()


def make_race(client, level="beginner", nickname=GEN, dev=None):
    r = client.post("/api/races", json={"level": level, "nickname": nickname, "device_id": dev or device()})
    assert r.status_code == 200, r.text
    return r.json()


def put_run(kind="ranked", level="beginner", score=100, dev=None, nickname="X", finished=None, status="verified",
            race=None, duration=60.0):
    """Insert a finished run straight into the database (for ordering / period tests)."""
    now = time.time() if finished is None else finished
    rid = secrets.token_hex(8)
    with closing(ranked._connect()) as con:
        con.execute(
            "INSERT INTO runs (id, token_hash, kind, race, level, seed, nickname, device_hash, created_at, "
            "finished_at, status, score, locks, duration_s) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (rid, "x", kind, race, level, 1, nickname, ranked._device_hash(dev or device()), now - duration, now,
             status, score, 3, duration))
        con.commit()
    return rid


# --------------------------------------------------------------------------- creating runs


def test_create_ranked_run_shape(client):
    run = start(client)
    assert set(run) == {"run_id", "run_token", "seed", "level", "kind"}
    assert len(run["run_id"]) == 16 and len(run["run_token"]) == 32 and int(run["run_token"], 16) >= 0
    assert 0 <= run["seed"] < 2**32 and run["level"] == "beginner" and run["kind"] == "ranked"


def test_run_token_and_device_are_stored_hashed(client):
    dev = device()
    run = start(client, dev=dev)
    with closing(ranked._connect()) as con:
        row = con.execute("SELECT * FROM runs").fetchone()
        dump = " ".join(str(v) for v in tuple(row))
    assert run["run_token"] not in dump and dev not in dump and row["device_hash"] == ranked._device_hash(dev)


def test_create_run_validation(client):
    assert start(client, nickname="", expect=422)
    assert start(client, nickname="x" * 21, expect=422)
    assert start(client, nickname="bad\x07name", expect=422)
    assert start(client, dev="ABC", expect=422)
    assert start(client, dev="G" * 32, expect=422)
    assert start(client, level=None, expect=422)                         # ranked needs a level
    assert client.post("/api/runs", json={"kind": "ranked", "level": "expert", "nickname": GEN,
                                          "device_id": device()}).status_code == 422
    assert client.post("/api/runs", json={"kind": "weekly", "level": "beginner", "nickname": GEN,
                                          "device_id": device()}).status_code == 422
    assert start(client, race="ABCDE", expect=422)                       # ranked runs have no race
    assert start(client, kind="race", level=None, expect=422)            # race needs a code
    assert start(client, nickname="  " + GEN + "  ")["run_id"]                   # trimmed
    assert start(client, nickname="Cánh Cụt Vui 17")["run_id"]


def test_run_rate_limit_is_30_per_hour_per_client(client):
    for _ in range(ranked.RUN_RATE_LIMIT):
        start(client)
    assert start(client, expect=429)
    r = client.post("/api/runs", json={"kind": "ranked", "level": "beginner", "nickname": GEN,
                                       "device_id": device()}, headers={"CF-Connecting-IP": "9.9.9.9"})
    assert r.status_code == 200   # another client is not affected


# --------------------------------------------------------------------------- recording and determinism


def test_invalid_run_fields_are_ignored_and_never_break_the_request(client):
    run = start(client)
    base = {"topic": "loops", "tier": 1, "level": "beginner", "kind": "rescue"}
    for extra in ({}, {"run_id": run["run_id"]}, {"run_id": run["run_id"], "run_token": "0" * 32},
                  {"run_id": "nope", "run_token": run["run_token"]}, {"run_id": "f" * 16, "run_token": "a" * 32}):
        r = client.post("/api/puzzle/next", json={**base, **extra})
        assert r.status_code == 200 and r.json()["topic"] == "loops"
    with closing(ranked._connect()) as con:
        assert con.execute("SELECT COUNT(*) FROM served").fetchone()[0] == 0
    pid = r.json()["id"]
    a = client.post(f"/api/puzzle/{pid}/answer", json={"option_id": "zz", "run_id": run["run_id"],
                                                        "run_token": run["run_token"]})
    assert a.status_code == 422                                    # an invalid answer is still a normal 422
    h = client.get(f"/api/puzzle/{pid}/hint", params={"level": 1, "run_id": run["run_id"], "run_token": "x"})
    assert h.status_code == 200


def test_next_hint_and_answer_are_recorded_for_a_valid_run(client):
    run = start(client, level="intermediate")
    auth = {"run_id": run["run_id"], "run_token": run["run_token"]}
    p = client.post("/api/puzzle/next", json={"topic": "loops", "tier": 2, "level": "beginner", "kind": "rescue",
                                              **auth}).json()
    pid = p["id"]
    for level in (1, 3, 2):
        assert client.get(f"/api/puzzle/{pid}/hint", params={"level": level, **auth}).status_code == 200
    row = bank.get_puzzle(pid)
    from .ranked_bot import answer_body
    first = client.post(f"/api/puzzle/{pid}/answer", json={**answer_body(row, False), **auth}).json()
    assert first["correct"] is False
    # a second, correct attempt does not rewrite history: the first checked answer counts
    assert client.post(f"/api/puzzle/{pid}/answer", json={**answer_body(row, True), **auth}).json()["correct"]
    with closing(ranked._connect()) as con:
        rec = dict(con.execute("SELECT * FROM served").fetchone())
    assert (rec["puzzle_id"], rec["kind"], rec["req_topic"], rec["req_tier"], rec["topic"]) \
        == (pid, "rescue", "loops", 2, "loops")
    assert rec["hint"] == 3 and rec["correct"] == 0 and rec["seq"] == 1
    # the run's level, not the request's, decides how the puzzle is shown (beginner would show 3 options)
    if p["type"] in ("fill_blank", "predict_output"):
        assert len(p["options"]) == 4


def test_a_race_puzzle_sequence_is_the_same_for_every_player(client):
    race = make_race(client)
    runs = [start(client, kind="race", level=None, race=race["code"]) for _ in range(2)]
    assert runs[0]["seed"] == runs[1]["seed"] == race["seed"] and runs[0]["level"] == race["level"]
    requests = [("loops", 1, "rescue", None), ("loops", 1, "rescue", None), ("variables", 2, "rescue", None),
                ("conditions", 3, "last_commit", None), ("loops", 1, "rescue", None)]
    seen = []
    for run in runs:
        ids = []
        for topic, tier, kind, tpl in requests:
            body = {"topic": topic, "tier": tier, "kind": kind, "level": "beginner",
                    "run_id": run["run_id"], "run_token": run["run_token"],
                    # the client's own exclude lists must not steer the pick
                    "exclude_ids": ids[:1] if run is runs[1] else [], "exclude_templates": []}
            ids.append(client.post("/api/puzzle/next", json=body).json()["id"])
        seen.append(ids)
    assert seen[0] == seen[1]
    assert len(set(seen[0])) == len(seen[0])      # the run's own history is excluded: no repeats


def test_debug_puzzles_are_deterministic_too(client):
    race = make_race(client)
    picks = []
    for _ in range(2):
        run = start(client, kind="race", level=None, race=race["code"])
        body = {"topic": "loops", "tier": 1, "kind": "debug", "template_id": "loops_range_fill", "level": "beginner",
                "run_id": run["run_id"], "run_token": run["run_token"]}
        r = client.post("/api/puzzle/next", json=body)
        assert r.status_code == 200, r.text
        picks.append(r.json()["id"])
    assert picks[0] == picks[1]


# --------------------------------------------------------------------------- finish


def test_full_ranked_run_is_replayed_and_scored_by_the_server(client):
    run = start(client, nickname="Mèo Vui 17")
    bot, moves, res = play_and_finish(client, run, wrong=(1,), hint_level=2)
    assert res["status"] == "verified"
    s = bot.g.summary()
    assert (res["score"], res["locks"], res["mistakes"], res["bugs_fixed"], res["best_streak"]) \
        == (s["score"], s["locks"], s["mistakes"], s["bugs_fixed"], s["best_streak"])
    assert res["score"] != 123 and s["score"] > 0 and s["locks"] >= 1 and s["mistakes"] == 1
    assert res["duration_s"] >= 0 and res["rank"] == {"day": 1, "week": 1, "all": 1} and "race" not in res
    again = client.post(f"/api/runs/{run['run_id']}/finish", json={"run_token": run["run_token"], "moves": moves})
    assert again.status_code == 409


def test_hints_cost_points_on_the_server(client):
    # two runs with the same seed would be needed for a strict comparison: use a race
    race = make_race(client, level="advanced")
    scores = []
    for hint in (0, 3):
        run = start(client, kind="race", level=None, race=race["code"])
        _, _, res = play_and_finish(client, run, hint_level=hint, max_moves=40)
        scores.append(res["score"])
    assert scores[0] > scores[1]


def test_finish_errors(client):
    run = start(client)
    url = f"/api/runs/{run['run_id']}/finish"
    assert client.post(url, json={"run_token": "0" * 32, "moves": []}).status_code == 403
    assert client.post("/api/runs/" + "0" * 16 + "/finish", json={"run_token": "0" * 32, "moves": []}).status_code == 404
    assert client.post("/api/runs/zzz/finish", json={"run_token": "0" * 32, "moves": []}).status_code == 404
    assert client.post(url, json={"run_token": run["run_token"]}).status_code == 422
    assert client.post(url, json={"run_token": run["run_token"], "moves": [1] * 5}).status_code == 422
    assert client.post(url, json={"run_token": run["run_token"], "moves": [{}] * 3001}).status_code == 422
    # still open after all of that
    assert client.post(url, json={"run_token": run["run_token"], "moves": []}).json() \
        == {"status": "rejected", "reason": "incomplete"}


def test_run_older_than_three_hours_cannot_finish(client):
    run = start(client)
    with closing(ranked._connect()) as con:
        con.execute("UPDATE runs SET created_at = ?", (time.time() - ranked.RUN_TTL_S - 5,))
        con.commit()
    r = client.post(f"/api/runs/{run['run_id']}/finish", json={"run_token": run["run_token"], "moves": []})
    assert r.status_code == 410
    # and an expired run no longer records anything
    p = client.post("/api/puzzle/next", json={"topic": "loops", "tier": 1, "kind": "rescue",
                                              "run_id": run["run_id"], "run_token": run["run_token"]})
    assert p.status_code == 200
    with closing(ranked._connect()) as con:
        assert con.execute("SELECT COUNT(*) FROM served").fetchone()[0] == 0


def test_rejected_runs_are_stored_and_never_ranked(client):
    run = start(client, nickname="Cáo Hiền 18")
    bot, moves, res = play_and_finish(client, run, max_moves=40, tamper=lambda m: m[:2] + [
        {"t": "place", "i": 0, "r": 0, "c": 0}] + m[2:])
    assert res["status"] == "rejected" and res["reason"] == "illegal_place"
    board = client.get("/api/leaderboard", params={"level": "beginner", "period": "all"}).json()
    assert board["entries"] == []
    with closing(ranked._connect()) as con:
        row = con.execute("SELECT status, reason, score, client_score FROM runs").fetchone()
    assert (row["status"], row["reason"], row["score"], row["client_score"]) == ("rejected", "illegal_place", 0, 123)


def test_puzzles_from_another_run_are_rejected(client):
    a, b = start(client), start(client)
    source_b = ApiSource(client, b)
    bot_a = Bot(a["seed"], a["level"], source_b)       # plays run a's game but with puzzles served to run b
    moves = bot_a.play(30)
    r = client.post(f"/api/runs/{a['run_id']}/finish", json={"run_token": a["run_token"], "moves": moves})
    assert r.json()["status"] == "rejected" and r.json()["reason"] == "puzzle_not_served"


def test_score_claimed_by_the_client_is_ignored(client):
    run = start(client)
    bot = Bot(run["seed"], run["level"], ApiSource(client, run))
    moves = bot.play(40)
    r = client.post(f"/api/runs/{run['run_id']}/finish",
                    json={"run_token": run["run_token"], "moves": moves, "client_score": 9_999_999})
    assert r.json()["score"] == bot.g.score
    assert client.post("/api/runs", json={}).status_code == 422


def test_a_long_move_list_is_not_cut_by_the_body_limit(client):
    run = start(client)
    moves = [{"t": "place", "i": 0, "r": 0, "c": 0}] * 3000      # ~100 KB, over the usual 64 KB limit
    r = client.post(f"/api/runs/{run['run_id']}/finish", json={"run_token": run["run_token"], "moves": moves})
    assert r.status_code == 200 and r.json()["status"] == "rejected"
    huge = {"run_token": run["run_token"], "moves": [{"t": "x" * 200}] * 3000}
    other = start(client)
    assert client.post(f"/api/runs/{other['run_id']}/finish", json=huge).status_code == 413
    # other endpoints keep the small limit
    assert client.post("/api/runs", content=b"x" * 70_000).status_code == 413


# --------------------------------------------------------------------------- leaderboard


def test_leaderboard_best_run_per_device_and_ordering(client):
    dev_a, dev_b = device(), device()
    now = time.time()
    put_run(score=300, dev=dev_a, nickname="A-low", finished=now - 30)
    put_run(score=900, dev=dev_a, nickname="A-high", finished=now - 20)
    put_run(score=500, dev=dev_b, nickname="B", finished=now - 10)
    put_run(score=500, dev=device(), nickname="C-later-tie", finished=now - 5)
    put_run(score=500, dev=device(), nickname="Race", kind="race", finished=now)            # not ranked
    put_run(score=999, dev=device(), nickname="Rejected", status="rejected")
    put_run(score=0, dev=device(), nickname="Zero")
    put_run(score=800, dev=device(), nickname="Other level", level="advanced")
    board = client.get("/api/leaderboard", params={"level": "beginner", "period": "all", "device_id": dev_b}).json()
    assert [(e["rank"], e["nickname"], e["score"]) for e in board["entries"]] \
        == [(1, "A-high", 900), (2, "B", 500), (3, "C-later-tie", 500)]
    assert set(board["entries"][0]) == {"rank", "nickname", "score", "locks", "at"}
    assert board["level"] == "beginner" and board["period"] == "all" and board["you"] == {"rank": 2, "score": 500}
    nobody = client.get("/api/leaderboard", params={"level": "beginner", "device_id": device()}).json()
    assert nobody["you"] is None and nobody["period"] == "all"
    assert client.get("/api/leaderboard", params={"level": "beginner", "device_id": "bad"}).json()["you"] is None
    assert client.get("/api/leaderboard", params={"level": "expert"}).status_code == 422
    assert client.get("/api/leaderboard", params={"level": "beginner", "period": "year"}).status_code == 422
    assert client.get("/api/leaderboard").status_code == 422


def test_leaderboard_is_limited_to_50_and_you_is_found_outside_it(client):
    me = device()
    for i in range(55):
        put_run(score=1000 - i, nickname=f"p{i}")
    put_run(score=1, dev=me, nickname="me")
    board = client.get("/api/leaderboard", params={"level": "beginner", "device_id": me}).json()
    assert len(board["entries"]) == 50 and board["entries"][-1]["score"] == 951
    assert board["you"] == {"rank": 56, "score": 1}


def test_leaderboard_periods_use_vietnam_time(client):
    day_start = ranked.period_start("day")
    week_start = ranked.period_start("week")
    assert day_start <= time.time() < day_start + 86400 and week_start <= day_start
    assert datetime.fromtimestamp(week_start, ranked.VN_TZ).weekday() == 0
    # 2026-11-18 is a Wednesday. 17:30 UTC on the 17th is 00:30 on the 18th in Vietnam.
    ts = datetime(2026, 11, 17, 17, 30, tzinfo=ranked.timezone.utc).timestamp()
    assert datetime.fromtimestamp(ranked.period_start("day", ts), ranked.VN_TZ).strftime("%Y-%m-%d %H:%M") \
        == "2026-11-18 00:00"
    assert datetime.fromtimestamp(ranked.period_start("week", ts), ranked.VN_TZ).strftime("%Y-%m-%d") == "2026-11-16"
    sunday = datetime(2026, 11, 22, 16, 59, tzinfo=ranked.timezone.utc).timestamp()   # 23:59 Sunday in Vietnam
    assert datetime.fromtimestamp(ranked.period_start("week", sunday), ranked.VN_TZ).strftime("%Y-%m-%d") \
        == "2026-11-16"
    monday = datetime(2026, 11, 22, 17, 0, tzinfo=ranked.timezone.utc).timestamp()    # 00:00 Monday in Vietnam
    assert datetime.fromtimestamp(ranked.period_start("week", monday), ranked.VN_TZ).strftime("%Y-%m-%d") \
        == "2026-11-23"
    assert ranked.period_start("all") == 0

    put_run(score=100, nickname="today")
    put_run(score=200, nickname="last-week", finished=week_start - 3600)
    put_run(score=300, nickname="yesterday", finished=day_start - 60)
    names = lambda period: [e["nickname"] for e in client.get(   # noqa: E731
        "/api/leaderboard", params={"level": "beginner", "period": period}).json()["entries"]]
    assert names("day") == ["today"]
    assert "yesterday" in names("week") or day_start == week_start    # Monday: yesterday is last week
    assert names("all") == ["yesterday", "last-week", "today"]


def test_best_run_is_chosen_within_the_period(client):
    dev = device()
    day_start = ranked.period_start("day")
    put_run(score=900, dev=dev, nickname="old", finished=day_start - 60)
    put_run(score=100, dev=dev, nickname="new")
    day = client.get("/api/leaderboard", params={"level": "beginner", "period": "day"}).json()
    allt = client.get("/api/leaderboard", params={"level": "beginner", "period": "all"}).json()
    assert [(e["nickname"], e["score"]) for e in day["entries"]] == [("new", 100)]
    assert [(e["nickname"], e["score"]) for e in allt["entries"]] == [("old", 900)]


# --------------------------------------------------------------------------- races


def test_create_race_and_read_it(client):
    host = device()
    race = make_race(client, level="intermediate", nickname="Gấu Sáng 19", dev=host)
    assert set(race) == {"code", "seed", "level", "url"}
    assert len(race["code"]) == 5 and set(race["code"]) <= CODE_CHARS and 0 <= race["seed"] < 2**32
    assert race["url"] == f"http://testserver/?race={race['code']}"
    info = client.get(f"/api/races/{race['code'].lower()}").json()
    assert set(info) == {"code", "level", "created_by", "created_at", "expires_at", "results", "playing"}
    assert info["code"] == race["code"] and info["level"] == "intermediate" and info["created_by"] == "Gấu Sáng 19"
    assert info["expires_at"] - info["created_at"] == 7 * 24 * 3600 and info["results"] == [] and info["playing"] == 0
    proxied = client.post("/api/races", json={"level": "beginner", "nickname": GEN, "device_id": device()},
                          headers={"X-Forwarded-Proto": "https", "X-Forwarded-Host": "sextax.example.com"}).json()
    assert proxied["url"] == f"https://sextax.example.com/?race={proxied['code']}"


def test_race_validation_and_rate_limit(client):
    assert client.post("/api/races", json={"level": "beginner", "nickname": "", "device_id": device()}).status_code == 422
    assert client.post("/api/races", json={"level": "beginner", "nickname": GEN, "device_id": "x"}).status_code == 422
    assert client.post("/api/races", json={"nickname": GEN, "device_id": device()}).status_code == 422
    assert client.get("/api/races/ZZZZZ").status_code == 404
    assert client.get("/api/races/bad").status_code == 404
    for _ in range(ranked.RACE_RATE_LIMIT):
        make_race(client)
    r = client.post("/api/races", json={"level": "beginner", "nickname": GEN, "device_id": device()})
    assert r.status_code == 429


def test_race_runs_take_level_and_seed_from_the_race(client):
    race = make_race(client, level="advanced")
    run = start(client, kind="race", level="beginner", race=race["code"])   # a level sent by the client is ignored
    assert run["level"] == "advanced" and run["seed"] == race["seed"] and run["race"] == race["code"]
    assert run["kind"] == "race"
    assert start(client, kind="race", level=None, race="ZZZZZ", expect=404)
    assert client.get(f"/api/races/{race['code']}").json()["playing"] == 1


def test_race_is_full_after_30_runs_and_expires(client):
    race = make_race(client)
    for _ in range(ranked.MAX_RACE_RUNS):
        start(client, kind="race", level=None, race=race["code"], dev=device())
        ranked.reset_rate_limits()
    assert start(client, kind="race", level=None, race=race["code"], expect=410)
    with closing(ranked._connect()) as con:
        con.execute("UPDATE races SET expires_at = ?", (time.time() - 1,))
        con.commit()
    assert client.get(f"/api/races/{race['code']}").status_code == 410
    assert start(client, kind="race", level=None, race=race["code"], expect=410)


def test_race_results_rank_by_score_then_duration_and_mark_your_row(client):
    race = make_race(client)
    me, other = device(), device()
    put_run(kind="race", race=race["code"], score=500, dev=other, nickname="Same", duration=50)
    put_run(kind="race", race=race["code"], score=500, dev=me, nickname="Same", duration=40)   # same nickname!
    put_run(kind="race", race=race["code"], score=300, dev=me, nickname="Same", duration=10)   # not its best
    put_run(kind="race", race=race["code"], score=900, dev=device(), nickname="Top", duration=99)
    put_run(kind="race", race=race["code"], score=9999, dev=device(), nickname="Rej", status="rejected")
    info = client.get(f"/api/races/{race['code']}").json()
    assert [(r["rank"], r["nickname"], r["score"], r["duration_s"]) for r in info["results"]] \
        == [(1, "Top", 900, 99.0), (2, "Same", 500, 40.0), (3, "Same", 500, 50.0)]
    assert all("you" not in r for r in info["results"])
    assert set(info["results"][0]) == {"rank", "nickname", "score", "locks", "mistakes", "duration_s", "finished_at"}
    mine = client.get(f"/api/races/{race['code']}", params={"device_id": me}).json()
    assert [r["you"] for r in mine["results"]] == [False, True, False]
    stranger = client.get(f"/api/races/{race['code']}", params={"device_id": device()}).json()
    assert [r["you"] for r in stranger["results"]] == [False, False, False]
    # race runs never reach the ranked leaderboard
    assert client.get("/api/leaderboard", params={"level": "beginner"}).json()["entries"] == []


def test_finishing_a_race_run_returns_the_race_and_skips_the_leaderboard(client):
    race = make_race(client)
    dev = device()
    run = start(client, kind="race", level=None, race=race["code"], dev=dev, nickname="Thỏ Nhanh 20")
    bot, _, res = play_and_finish(client, run, max_moves=40)
    assert res["status"] == "verified" and res["rank"] is None
    assert res["race"]["code"] == race["code"]
    assert [(r["nickname"], r["score"]) for r in res["race"]["results"]] == [("Thỏ Nhanh 20", bot.g.score)]
    assert res["race"]["results"][0]["you"] is True and res["race"]["playing"] == 0
    assert client.get("/api/leaderboard", params={"level": "beginner"}).json()["entries"] == []


def test_ranked_rank_counts_better_devices(client):
    put_run(score=10_000, nickname="Giant")
    run = start(client, nickname="Cú Tím 21")
    _, _, res = play_and_finish(client, run, max_moves=40)
    assert res["status"] == "verified" and res["score"] > 0
    assert res["rank"] == {"day": 2, "week": 2, "all": 2}
    board = client.get("/api/leaderboard", params={"level": "beginner", "device_id": ""}).json()
    assert [e["nickname"] for e in board["entries"]] == ["Giant", "Cú Tím 21"]


# --------------------------------------------------------------------------- purge


def test_abandoned_and_old_runs_are_purged_lazily(client):
    old_open = start(client)
    old_done = put_run(finished=time.time() - ranked.KEEP_FINISHED_S - 10)
    fresh_done = put_run()
    race = make_race(client)
    start(client, kind="race", level=None, race=race["code"])
    with closing(ranked._connect()) as con:
        con.execute("UPDATE runs SET created_at = ? WHERE id = ?", (time.time() - ranked.RUN_TTL_S - 10, old_open["run_id"]))
        con.execute("INSERT INTO served (run_id, seq, puzzle_id, kind, topic, template_id) VALUES (?,?,?,?,?,?)",
                    (old_open["run_id"], 1, "p", "rescue", "loops", "t"))
        con.execute("UPDATE races SET expires_at = ?", (time.time() - 1,))
        con.commit()
    start(client)       # any write purges
    with closing(ranked._connect()) as con:
        ids = {r["id"] for r in con.execute("SELECT id FROM runs")}
        assert old_open["run_id"] not in ids and old_done not in ids and fresh_done in ids
        assert con.execute("SELECT COUNT(*) FROM races").fetchone()[0] == 0
        assert con.execute("SELECT COUNT(*) FROM served").fetchone()[0] == 0
        assert not con.execute("SELECT 1 FROM runs WHERE race IS NOT NULL").fetchall()
