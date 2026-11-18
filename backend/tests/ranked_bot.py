"""Test helper: a bot that plays Code Rescue with the Python engine and a pluggable puzzle source.

The bot behaves like the browser (frontend/js/main.js + runlog.js): it places the first legal piece it finds,
solves locks with whatever puzzle the source serves, and records the move list in the format of
docs/ranked-and-race.md. ``OfflineSource`` fabricates the server's records; ``ApiSource`` talks to the real
endpoints through a TestClient.
"""
from __future__ import annotations

from app import bank
from app import rescue_engine as E


class OfflineSource:
    """Serves synthetic puzzles and keeps the records a server would hold."""

    def __init__(self, hint_every: int = 0):
        self.records: list[dict] = []
        self.hint_every = hint_every

    def serve(self, kind, topic, tier, template, want_correct):
        seq = len(self.records) + 1
        hint = (seq % 4) if self.hint_every and seq % self.hint_every == 0 else 0
        rec = {"id": f"x{seq}", "seq": seq, "kind": kind, "req_topic": topic, "req_tier": tier,
               "req_template": template, "topic": topic, "template_id": template or f"{topic}_t{seq % 3}",
               "hint": hint, "correct": want_correct}
        self.records.append(rec)
        return rec["id"], want_correct


class ApiSource:
    """Serves puzzles through POST /api/puzzle/next (with the run fields) and answers them for real."""

    def __init__(self, client, run, hint_level=0):
        self.client, self.run, self.hint_level = client, run, hint_level
        self.auth = {"run_id": run["run_id"], "run_token": run["run_token"]}
        self.served: list[dict] = []

    def serve(self, kind, topic, tier, template, want_correct):
        body = {"topic": topic, "tier": tier, "level": self.run["level"], "kind": kind, **self.auth}
        if template:
            body["template_id"] = template
        r = self.client.post("/api/puzzle/next", json=body)
        assert r.status_code == 200, r.text
        pid = r.json()["id"]
        self.served.append(r.json())
        if self.hint_level:
            h = self.client.get(f"/api/puzzle/{pid}/hint", params={"level": self.hint_level, **self.auth})
            assert h.status_code == 200, h.text
        row = bank.get_puzzle(pid)
        res = self.client.post(f"/api/puzzle/{pid}/answer", json={**answer_body(row, want_correct), **self.auth})
        assert res.status_code == 200, res.text
        return pid, res.json()["correct"]


def answer_body(row, correct):
    d = row["data"]
    if row["type"] == "parsons":
        if correct:
            return {"order": [{"line_id": s["line_id"], "indent": s["indent"]} for s in d["solution"]]}
        lines = [{"line_id": x["id"], "indent": 0} for x in reversed(d["lines"])]
        return {"order": lines}
    for o in d["options"]:
        if o["correct"] == correct:
            return {"option_id": o["id"]}
    raise AssertionError("puzzle has no option for this outcome")


class Bot:
    def __init__(self, seed, level, source, wrong=()):
        self.g = E.RescueGame(seed, level)
        self.source = source
        self.wrong = set(wrong)  # ordinals (0-based) of the puzzles to answer wrongly
        self.asked = 0
        self.moves: list[dict] = []
        self.fix_bugs = False

    def ask(self, kind, topic, tier, template=None):
        want = self.asked not in self.wrong
        self.asked += 1
        return self.source.serve(kind, topic, tier, template, want)

    def first_legal(self):
        for i, p in enumerate(self.g.tray):
            if p is None:
                continue
            for r in range(E.SIZE):
                for c in range(E.SIZE):
                    if self.g.can_place(p, r, c):
                        return i, r, c
        raise AssertionError("no legal placement")

    def end(self, reason):
        self.moves.append({"t": "end", "reason": reason})

    def settle(self):
        g = self.g
        g.settle()
        while g.stuck:
            g.last_commit_used = True
            g.stuck = False
            topic = g.last_commit_topic()
            pid, ok = self.ask("last_commit", topic, 3)
            self.moves.append({"t": "last_commit", "puzzle": pid})
            if not ok:
                g.fail_last_commit(topic, f"{topic}_t0")
                self.end("nofit")
                return
            g.clear_fullest_rows()
            g.settle()
        if g.phase == "over":
            self.end(g.end_reason)

    def solve_lock(self):
        g = self.g
        lk = g.lock
        use_dbg = g.items["debugger"] > 0
        if use_dbg:
            g.items["debugger"] -= 1
        free = g.free_hint_level(use_dbg)
        tier = 3 if lk["boss"] else lk["tier"]
        ids, failed = [], None
        for _ in range(2 if lk["boss"] else 1):
            pid, ok = self.ask("rescue", lk["topic"], tier)
            ids.append(pid)
            if not ok:
                failed = pid
                break
        move = {"t": "lock", "puzzles": ids}
        if use_dbg:
            move["debugger"] = True
        self.moves.append(move)
        return lk, free, tier, failed

    def play(self, max_moves=200):
        g = self.g
        while g.phase != "over" and len(self.moves) < max_moves:
            if g.phase == "locked":
                self.resolve_lock()
            elif self.fix_bugs and g.bug_lines:
                self.fix_bug()
            else:
                i, r, c = self.first_legal()
                self.moves.append({"t": "place", "i": i, "r": r, "c": c})
                if g.place(i, r, c)["lock"]:
                    g.phase = "locked"
                else:
                    self.settle()
        if g.phase != "over":
            self.end("quit")
        return self.moves

    def fix_bug(self):
        g = self.g
        bl = g.bug_lines[0]
        pid, ok = self.ask("debug", bl["topic"], 1, bl["template_id"])
        self.moves.append({"t": "bugfix", "bug": bl["id"], "puzzle": pid})
        if ok:
            g.fix_bug(bl["id"])
            self.settle()
        else:
            g.apply_debug_wrong(bl["topic"], bl["template_id"])
            self.end("crash")

    def resolve_lock(self):
        g = self.g
        lk, free, tier, failed = self.solve_lock()
        if failed is None:
            # the hint level of a lock is read back from the server's records; the offline source / API
            # tests open at most one hint level for every puzzle, so use the recorded one
            max_hint = self.source_hint(lk, tier)
            g.apply_correct(g.base_for(lk), max_hint, free, lk["count"])
            g.finish_lock()
            self.settle()
        elif g.apply_wrong(lk["topic"], self.template_of(failed)) == "bug":
            self.settle()
        else:
            self.end("crash")

    # ---- what the source knows about the puzzles it served ----
    def source_hint(self, lk, tier):
        ids = self.moves[-1]["puzzles"]
        return max((self.hint_of(pid) for pid in ids), default=0)

    def hint_of(self, pid):
        if isinstance(self.source, OfflineSource):
            return next(r["hint"] for r in self.source.records if r["id"] == pid)
        return self.source.hint_level

    def template_of(self, pid):
        if isinstance(self.source, OfflineSource):
            return next(r["template_id"] for r in self.source.records if r["id"] == pid)
        return bank.get_puzzle(pid)["template_id"]
