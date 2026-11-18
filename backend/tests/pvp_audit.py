"""Autoplay deterministic matches and independently check the PvP diagnostic evidence.

Run from backend: python -m tests.pvp_audit --games 100 --log pvp-audit.jsonl
Uses the real match engine and bot controller with a virtual clock, without touching live accounts.
"""
from __future__ import annotations

import argparse
import json
import logging
from collections import Counter
from pathlib import Path

from app import pvp
from . import misaki_sim


class Evidence(logging.Handler):
    def __init__(self):
        super().__init__()
        self.events: list[dict] = []

    def emit(self, record):
        self.events.append(json.loads(record.getMessage().removeprefix("pvp ")))


def audit(events: list[dict]) -> dict:
    incoming = Counter()
    opponent_rows = Counter()
    landings = {}
    for e in events:
        if e["event"] == "incoming":
            incoming[e["side"]] += e["rows"]
            assert incoming[e["side"]] == e["received"], e
            if e["source"] == "opponent":
                opponent_rows[e["sender"]] += e["rows"]
        elif e["event"] == "landing":
            assert e["rows"] == e["pending_before"] > 0, e
            board = [list(row) for row in e["board_before"]]
            for r, c in e["cells"]:
                assert board[r][c] == ".", e
                board[r][c] = "#"
            placed = ["".join(row) for row in board]
            k = e["rows"]
            top_out = k > 8 or any(cell != "." for row in placed[:k] for cell in row)
            assert (e["end_reason"] == "topped_out") == top_out, e
            expected = placed if top_out else placed[k:] + ["BBBBBBBB"] * k
            assert e["board_after"] == expected, e
            landings[e["side"]] = e
    end = next(e for e in events if e["event"] == "end")
    for player in end["players"]:
        assert player["received"] == incoming[player["side"]], end
        assert player["sent"] == opponent_rows[player["side"]], end
    result = {"seed": end["seed"], "reason": end["reason"], "elapsed_s": end["elapsed_s"]}
    if end["reason"] == "topped_out":
        landing = landings[1 - end["winner"]]
        assert landing["end_reason"] == "topped_out", end
        result.update(rows=landing["rows"], received=landing["received"],
                      occupied_before=sum(cell != "." for row in landing["board_before"] for cell in row))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--games", type=int, default=48)
    parser.add_argument("--seed", type=int, default=1000)
    parser.add_argument("--log", type=Path)
    args = parser.parse_args()
    if args.games < 1:
        parser.error("--games must be positive")
    capture = Evidence()
    logger = pvp.diagnostics
    original_level = logger.level
    logger.setLevel(logging.INFO)
    logger.addHandler(capture)
    results = []
    try:
        for k in range(args.games):
            capture.events = []
            levels = (k % 4 + 1, (k // 4) % 4 + 1)
            match = misaki_sim.run_match(levels, args.seed + k)
            assert match.phase == "over", f"match {args.seed + k} timed out"
            results.append(audit(capture.events))
            if args.log:
                with args.log.open("a", encoding="utf-8") as output:
                    for event in capture.events:
                        output.write(json.dumps(event, separators=(",", ":")) + "\n")
    finally:
        logger.removeHandler(capture)
        logger.setLevel(original_level)
    one_line = [r for r in results if r.get("rows") == 1]
    print(json.dumps({"games": len(results), "violations": 0,
                      "end_reasons": dict(Counter(r["reason"] for r in results)),
                      "one_line_topouts": len(one_line),
                      "one_total_received_topouts": sum(r["received"] == 1 for r in one_line),
                      "examples": one_line[:5]}, indent=2))


if __name__ == "__main__":
    main()
