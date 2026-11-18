# Ranked runs and races (Code Rescue)

Contract shared by the backend and the frontend. No accounts: a player is a nickname plus a random
device id kept in the browser. The rule that makes the ranking trustworthy:

> **The server never accepts a score.** It deals the pieces from a seed, picks every puzzle, checks
> every answer and records every hint opened. At the end the browser sends only its list of moves;
> the server replays the whole game with the same rules (`backend/app/rescue_engine.py`, a port of
> `frontend/js/game.js` + `pieces.js`) and computes the score itself.

Only `mode: 'rescue'` rules apply to ranked runs and races (two wrong answers end the run, no practice
bug-line lifetime, no focus topic).

## 1. Identity

- `device_id`: 32 lowercase hex chars, generated once in the browser (`localStorage`
  `syntaxstack.device`). Stored server-side only as SHA-256.
- `nickname`: always a generated name `"<animal> <adjective> <NN>"` (e.g. `Mèo Xanh 42`, at most 20 chars),
  fetched from `GET /api/nickname` (`{nickname}`, 60 per minute per client IP, then 429). `POST /api/runs`
  and `POST /api/races` accept only names that match that format exactly (after Unicode NFC normalisation)
  against the word lists in `backend/content/nickname_words.yaml`; anything else is
  `422 "Hãy dùng tên được tạo ngẫu nhiên."`. There is therefore no free text on the public leaderboard.
  Stored in `localStorage` `syntaxstack.nickname`. Not unique.

## 2. Determinism

- RNG: `mulberry32(seed)` exactly as `mulberry()` in `frontend/js/main.js` (32-bit int arithmetic,
  `Math.imul`, `>>> 0`, divide by 4294967296). Python must reproduce the same float sequence.
- `seed`: unsigned 32-bit int chosen by the server.
- The browser creates the game with `newGame({ mode: 'rescue', level, rng: mulberry(seed) })` and
  must not call `s.rng()` anywhere else. Every consumer of `s.rng` (tray refill, lock topic tie-break,
  Last Commit topic) is mirrored in the engine in the same order.
- Puzzles: inside a run, `POST /api/puzzle/next` ignores the client's randomness and picks from the
  same pool as today, but with an RNG derived from `(seed, kind, topic, tier, template_id, n)` where `n`
  counts earlier requests of that same `(kind, topic, tier, template_id)` in the run. Two racers who
  reach the same lock in the same order get the same puzzle. `exclude_ids` / `exclude_templates` are
  **ignored inside a run**: the server uses its own history instead (the last 500 puzzle ids it served in
  the run, and the templates of the last 3), which is exactly what an honest client sends. The pick also
  uses the run's level, not the request's. Candidates are sorted by id before the seeded pick, so the same
  bank gives the same puzzle on every machine.

## 3. Run lifecycle

### `POST /api/runs`
Body `{kind: "ranked"|"race", level: "beginner"|"intermediate"|"advanced", nickname, device_id, race?: "<code>"}`.
For `race`, `level` and `seed` come from the race. → `200 {run_id, run_token, seed, level, kind, race?}`.
`run_token` is 32 hex, stored hashed. 404 unknown race, 410 race expired/full (30 runs), 422 bad
nickname/device id, 429 more than 30 runs per hour per client IP.

### During the run
The existing endpoints accept optional `run_id` + `run_token` (body for POST, query for GET). With a
valid pair the server **records**, in order:
- `POST /api/puzzle/next` → the served puzzle id, kind, topic, tier (deterministic pick, §2).
- `GET /api/puzzle/{id}/hint?level=n` → max hint level opened for that puzzle in this run.
- `POST /api/puzzle/{id}/answer` → the verified result (correct, wrong) of each attempt.
Invalid run fields are ignored (the request still works, nothing is recorded). Room fields keep working
alongside.

### `POST /api/runs/{run_id}/finish`
Body `{run_token, moves: [...], client_score}` (`client_score` is only logged for diagnostics).
`moves` (≤ 3000 entries), in the order they happened:

| Move | Meaning |
| --- | --- |
| `{"t":"place","i":0,"r":3,"c":2}` | `Game.place(s, i, r, c)` |
| `{"t":"lock","puzzles":["id", ...]}` | the current lock was resolved with these served puzzle ids: 1 for a normal lock; for a boss lock 2, **or 1 when the first puzzle was answered wrong** (the second is never served) |
| `{"t":"lock", ..., "debugger": true}` | the Debugger item was consumed for this lock (free hint level 2). The browser spends a Debugger automatically whenever it owns one, so the flag must be present exactly when the replayed state owns one (`debugger_mismatch` otherwise) |
| `{"t":"undo"}` | Undo item used while locked (restores the snapshot, lock cancelled) |
| `{"t":"bomb","r":4,"c":4}` | Bomb item |
| `{"t":"shuffle"}` | Shuffle item |
| `{"t":"bugfix","bug":1,"puzzle":"id"}` | tapped bug line `bug` and answered the served debug puzzle |
| `{"t":"last_commit","puzzle":"id"}` | no piece fits: the Last Commit puzzle |
| `{"t":"end","reason":"crash"|"nofit"|"quit"}` | last move. `crash` / `nofit` must match how the replayed game really ended (a second wrong answer; no piece fits and Last Commit was skipped, failed or already used); `quit` is a player leaving early and is scored as it stands. If the replayed game already ended by itself (crash, or `nofit` after Last Commit was used) the `end` move may be left out |

The engine replays every move. Outcomes of puzzles (correct/wrong, hints) come **only** from the
server's records for this run (the first checked answer to a puzzle counts, the highest hint level opened
counts); a move that references a puzzle not served in this run, served for a different
kind/topic/tier/template than the replayed state requires (a Debug puzzle is asked with the bug line's
`template_id` and tier 1, every other kind with no `template_id`), not answered, already used by an earlier
move, or older than the previous one used (puzzles are consumed in serving order; served puzzles that are
never used, e.g. a lost response, are fine) makes the run invalid. Any illegal move (piece does not fit,
item not owned, lock pending when placing, no piece fits but something other than Last Commit / end,
moves after the end) makes the run invalid. While no piece fits and Last Commit is unused, the only legal
moves are `last_commit` and `end nofit`. Last Commit's topic is drawn from the game RNG, so the client asks
for it with `kind: "last_commit"`, `tier: 3` and the topic `Game.lastCommitTopic` returned.

→ `200 {status: "verified", score, locks, mistakes, bugs_fixed, best_streak, duration_s, rank: {day, week, all} | null, race?: {...same as GET race, with "you" marked}}`
or `200 {status: "rejected", reason}` (stored, never ranked). 409 already finished, 403 bad token, 404 unknown
run, 410 run older than 3 hours, 413 body over 192 KB (the one endpoint with a bigger limit than the usual
64 KB), 422 malformed body. `duration_s` is server time from create to finish (seconds, 1 decimal).

- `locks` = locks cleared with a correct answer. `mistakes` = wrong answers given (lock, Debug and Last
  Commit puzzles), the number the end screen shows; it is not the 0/1 warning state.
- `rank` is `null` for race runs and for ranked runs with score 0; otherwise the position of this device's
  best verified ranked run in each period (it can be better than this run).
- `reason` codes (stable strings): `bad_level`, `too_many_moves`, `bad_move`, `moves_after_end`,
  `illegal_place`, `illegal_phase`, `no_lock`, `bad_lock`, `debugger_mismatch`, `item_not_owned`,
  `bomb_empty`, `bad_bug`, `stuck`, `not_stuck`, `bad_end`, `incomplete`, `puzzle_not_served`,
  `puzzle_mismatch`, `puzzle_reused`, `puzzle_order`, `puzzle_not_answered`.

## 4. Leaderboard

`GET /api/leaderboard?level=beginner|intermediate|advanced&period=day|week|all&device_id=<optional>`
→ `{level, period, entries: [{rank, nickname, score, locks, at}], you: {rank, score} | null}`.
Top 50, verified **ranked** runs with a score above 0, best run per device per period (ties: earlier run
first). `at` is the finish time in Unix seconds; `you` is that device's own best run in the period and its
rank even outside the top 50 (`null` without a valid `device_id` or without a run in the period).
Day/week boundaries in Asia/Ho_Chi_Minh (UTC+7); week starts Monday.

## 5. Races

- `POST /api/races` `{level, nickname, device_id}` → `{code, seed, level, url}` (`code`: 5 chars
  from the classroom alphabet; `url` = `<public base>/?race=<code>`, built like the classroom join URL).
  10 races per hour per client.
- `GET /api/races/{code}?device_id=<optional>` → `{code, level, created_by, created_at, expires_at, results: [{rank, nickname, score, locks, mistakes, duration_s, finished_at, you?}], playing: n}`. Timestamps are Unix seconds. Verified race runs only, best per device, ranked by score then shorter duration. With a valid `device_id` every result row carries `you` (`true` only for that device's row; nicknames are not unique); without one the field is omitted. `playing` = race runs started in the last 3 hours and not finished. Expires 7 days after creation (404 unknown, 410 expired); 30 runs max.
- Race runs never appear on the ranked leaderboard (the seed is shared, so it is not a fair ranked game).

## 6. Storage

`ranked.sqlite` next to `SYNTAX_STACK_CUSTOM_DB` (on the Docker volume), override with
`SYNTAX_STACK_RANKED_DB`. Abandoned runs (no finish after 3 hours) are purged lazily (on the next run or
race created); finished runs are kept 90 days, race data (race and its runs) 7 days.

## 7. Limits of the trust model

The server controls the deal, the puzzle picks, the checking of every answer and the arithmetic, so a
client cannot claim a score, skip a puzzle, answer twice and keep the better result, or use an item it
does not own. It cannot stop a player from learning answers or hints outside the run (the answer and hint
endpoints also work without `run_id`), so this is a fair-play deterrent for a classroom, not protection
against a determined cheater.

## 8. Tests

`backend/tests/test_rescue_engine.py` runs `backend/tests/js_harness/play.mjs` (needs `node`), which plays
hundreds of random legal games with the real `frontend/js/game.js` and requires the Python replay to reach
the identical final state. Change a rule in `game.js` or `pieces.js` and the same rule in
`backend/app/rescue_engine.py`, or that test fails. `backend/tests/test_ranked.py` covers the HTTP side.
