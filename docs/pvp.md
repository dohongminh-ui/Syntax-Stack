# Real-time 1v1 (Code Rescue "Đối kháng")

Contract shared by the rules/server work and the frontend work. Builds on ranked play
(`docs/ranked-and-race.md`): same seeded pieces, same server-picked puzzles, same Python rules engine.
No accounts: generated nicknames (`backend/app/nicknames.py`) and the browser device id.

## 1. The game in one paragraph

Two players play Code Rescue on their own boards, at the same time, dealt the **same pieces** (same
seed). When you clear a lock by answering its puzzle correctly, you **send bug lines**: rows of ERR
blocks that rise from the bottom of your opponent's board, like garbage in a falling-block versus game.
Incoming bug lines wait in a queue first, and lines you clear cancel your own queue before anything is
sent. The queue lands after your next placement, or by itself 4 seconds after it started (2 seconds in
overtime) while no lock is open, so standing still does not save you. A lock must be answered within 40 seconds
(70 for a boss lock), or it turns into one of your own bug lines. Opening a puzzle pauses **your** board only;
your opponent keeps playing, so thinking speed is the skill. You lose when none of your pieces fits.

## 2. Rule changes (`mode: 'pvp'`)

These live in `frontend/js/game.js` **and** `backend/app/rescue_engine.py`, changed together, kept in
lockstep by the golden test (§7). Everything not listed works as in `mode: 'rescue'`.

1. **No crash on mistakes.** A wrong lock answer turns the lock into one of your own bug lines (as the
   first mistake does in Rescue), every time. There is no second-mistake crash and no Last Commit.
2. **Lines sent** by a correct lock answer: `SEND = [0, 1, 2, 3, 4]` indexed by `min(lock.count, 4)`,
   plus 1 if the answer was clean (no paid hint) and the streak after it is ≥ 3. A boss lock answered
   correctly sends 4 + streak bonus.
3. **Cancelling.** Lines you would send first cancel your own pending incoming lines, one for one; only
   the remainder is sent.
4. **Pending queue.** Incoming lines are held in `s.pending` (a list of `{topic, templateId}` entries,
   one per row). They **land after your next placement that does not create a lock**, all at once, **or by
   themselves** when the landing timer runs out. A placement that creates a lock keeps them pending until that
   lock is resolved (answer, timeout or undo), then they land on the next placement that does not create a
   lock (or by the timer). Lines that arrive while a lock is open are queued behind the older ones.
   **Landing timer:** it starts when the queue goes from empty to non-empty, with a delay of `LAND_DELAY_S` = 4.0 s
   (`LAND_DELAY_OVERTIME_S` = 2.0 s when the timer starts at or after 4:00 of match time). More rows arriving
   while it runs do **not** extend it. When the queue empties (a placement landed it, or your clears cancelled all
   of it) the timer is cleared. When it runs out and you have no lock open, every pending row lands at once with
   the same rules as a placement landing (rule 5), then the no-fit check runs (rule 7, it can end the match). While
   a lock is open the timer is held (the deadline is not moved): if it has passed when the lock is resolved, the
   rows land on the next server tick. Placing early still lands the rows immediately. A timed landing leaves no undo
   snapshot either. A player whose socket dropped is frozen (section 4): the deadline moves back by the time away.
5. **Landing** k rows: every existing cell moves up k rows (existing bug lines move with their cells). Any
   cell pushed above row 0 is **destroyed** (a bug line pushed off goes with it). This is never fatal: you
   lose only when no piece fits (rule 6). With more than 8 rows the oldest are pushed off too. The bottom k rows are filled with ERR bug cells: each row is a full row of
   bug cells and its own bug line (`bugLines` entry, new ids in queue order) with the sender's topic and
   template, so it can be tapped and fixed with a Debug puzzle like any bug line. The oldest row ends up
   on top of the new block, the newest in row 7. A lock in progress is impossible at this moment (see 4).
   After a landing there is no undo snapshot.
6. **Fixing** a bug line (correct Debug answer) clears it as in Rescue, sends nothing, and keeps the
   Debugger item reward. A wrong Debug answer: the line stays (no crash).
7. **No fit:** if none of your tray pieces fits anywhere, you lose (`reason: 'nofit'`).
8. **Overtime:** from 4:00 of match time, 1 bug line is added to **both** players' pending queues every
   20 s (topic: a random topic from a server RNG derived from the match seed; template: none → the
   debug puzzle for that topic's `*_bug` template). This guarantees a match ends.
9. Score is still computed (it is the tiebreak shown at the end) but nobody is ranked by it.
10. Items work as in Rescue (bomb, shuffle, undo, debugger). Undo restores the snapshot taken before
    the placement that created the lock, **including the pending queue as it was at that time; rows that
    arrived since are re-queued behind it** (`pending = snapshot.pending + rows received since`, so nothing
    is lost and undo cannot dodge incoming rows). The server only allows Undo while the lock's puzzle has not
    been opened yet.
11. **Debugger** works as in Rescue: it is spent automatically on the next lock that opens while owned,
    which is when the server serves the first puzzle of that lock (`state.you.lock.debugger` is then
    `true`, `items.debugger` drops by one) and gives free hint level 2 for that lock.
12. **Boss locks** (4+ lines) are two sequential puzzles as in Rescue: the second is only served when the
    first was answered correctly (a wrong first answer ends the lock with one bug line). They send 4 lines
    plus the streak bonus.
13. **Same pieces.** Both players are dealt from the same seed. Breaking a lock-topic tie draws no random
    number in pvp (the first tied topic in row-major order of the lock cells wins), so the piece sequence
    only depends on how many pieces a player drew (a Shuffle draws 3 more).
14. **Lock limit.** A lock must be answered within `LOCK_LIMIT_S` = 40 s, or `LOCK_LIMIT_BOSS_S` = 70 s for a
    boss lock (two puzzles), counted from the moment the lock was created, whether or not its puzzle was ever
    opened. When it runs out the lock is resolved exactly as a **wrong answer** (rule 1): it turns into one of
    your own bug lines (topic and template of the open puzzle, or the lock's topic with template `<topic>_bug` when
    none was opened), the streak resets, nothing is sent. A puzzle that was open for that lock is marked answered: a
    late answer is checked as always but not applied, and a new `puzzle/next` for it is `409` (no lock). Undo clears
    the lock's deadline, a new lock gets a new one. A landing that was due is done on the next tick (rule 4).

The two timers (rule 4 landing timer, rule 14 lock limit) belong to the **match layer** (`backend/app/pvp.py`, on the
match clock): they only call the existing engine functions (`land_pending` + `check_no_fit`, and the wrong-answer
path of `pvp_resolve_lock`), so `game.js` needs no change. The golden replay knows them as the events `land` and
`lock_timeout` (section 7).

### `game.js` interface for PvP (owned by the rules work; the frontend builds against it)

- `newGame({ mode: 'pvp', level, rng })` → state gains `pending: []` (incoming rows, oldest first),
  `sent: 0`, `received: 0`.
- `place(s, i, r, c)` → in pvp also returns `landed` (rows that landed, 0 if none) (landing
  destroys cells pushed above row 0 but never ends the game; a following no-fit check may).
- `applyCorrect(s, {...})` → in pvp also returns `send` (lines actually sent after cancelling) and
  `cancelled` (own pending rows cancelled). The caller (server) delivers `send` to the opponent.
- `queueIncoming(s, entries)` appends `{topic, templateId}` rows to `s.pending`; `s.received += n`;
  returns n (0 outside pvp or when the game is over).
- `landPending(s)` lands every pending row (called by `place`); returns the number of rows, also when
  the game ended. `PVP_SEND` is the send table.
- `applyWrong`, `fixBug`, `applyDebugWrong` follow rule 1 / 6 in pvp (never crash).
- No-fit detection: `checkNoFit(s)` (returns true when it ended the game) runs by itself, in pvp only, at the
  end of `place` (when no lock was made, after landing), `finishLock`, `applyWrong`, `fixBug` and `shuffle`:
  `anyFit(s)` false → `s.phase = 'over'`, `s.endReason = 'nofit'` (the server decides it, the frontend
  shows the end).
- `place` in pvp returns `{placed, lock, expired, landed}`; the caller still sets `phase = 'locked'` when
  `lock` is set. `applyCorrect` returns `{..., send, cancelled}`; `s.sent` counts `send` (after cancelling).
- Undo restores `pending` from the snapshot and re-queues rows that arrived since (rule 10).
- Rescue, practice and ranked behaviour is unchanged; every addition is behind `s.mode === 'pvp'`.

## 3. Match lifecycle

### Matchmaking (HTTP)
- `POST /api/pvp/queue {level, nickname, device_id}` → `{ticket}` and joins the quick-match queue for
  that level. Pairing is first-come within a level. `DELETE /api/pvp/queue/{ticket}` leaves the queue.
- `POST /api/pvp/private {level, nickname, device_id}` → `{code, ticket, url}` (code: classroom
  alphabet, 5 chars; `url` = `<public base>/?duel=<code>`). The second player calls
  `POST /api/pvp/private/{code}/join {nickname, device_id}` → `{ticket}`. 404 unknown, 409 full,
  410 expired (10 minutes without a second player; the code answers 410 for an hour after that).
  Codes are case-insensitive.
- `POST /api/pvp/bot {level, nickname, device_id, misaki?, training?}` → `{ticket}`: an immediate match against the
  built-in bot, always labelled as a bot in the UI. With `misaki` it is Misaki of that ladder level (section 5);
  without it, the generic "Máy" + a generated animal name (the same search AI, at the ladder level that matches
  `level`: beginner 1, intermediate 2, advanced 3).
- Nicknames must be generated names (422 as for ranked). Rate limit: 60 requests per hour per client IP
  across queue / private / join / bot (429).
- A queued ticket has to open its socket within 15 s and may be away at most 15 s, or it is dropped; it waits
  at most 5 minutes (`error queue_timeout`). A ticket is never paired with a ticket of the same device.
  `DELETE /api/pvp/queue/{ticket}` → 204 (404 unknown ticket; 409 once the match has started). If the ticket
  was already paired but not started, the match is dissolved and the other player gets
  `error opponent_left`.
- Server limits: 200 live matches (`503` when full), 2000 tickets.

### Live connection
`GET /api/pvp/ws?ticket=<ticket>` upgrades to a WebSocket. One socket per player. All messages are JSON
`{"t": "<type>", ...}`. The **server is authoritative**: it runs both games with the rules engine and
the browser renders what the server says. The browser may predict its own placement locally (same
rules, same seed) and must accept the server's state when it differs.

One socket per ticket: opening a second socket with the same ticket replaces the first (it gets
`error replaced` and is closed with code 4001); that is also how a reconnect after a reload works. A
unknown/ended ticket gets `error bad_ticket` and close code 4404 (after a server restart every ticket is
unknown, so the client should treat `bad_ticket` on a reconnect as `server_restart`). `ready` may be sent
as soon as the socket is open (also before an opponent is found) and survives a reconnect; the countdown
(3 s) starts when both players are connected and ready. Two paired players who are not both ready within
60 s: `error lobby_timeout` (match cancelled).

Client → server:

| `t` | Fields | Meaning |
| --- | --- | --- |
| `ready` | | in the lobby, ready to start |
| `place` | `i, r, c, received?` | place tray piece `i` at (r, c); `received` is the last displayed `state.you.received` |
| `bomb` | `r, c` | use Bomb |
| `shuffle` | | use Shuffle |
| `undo` | | use Undo while a lock is pending |
| `resign` | | give up (immediate loss) |
| `ping` | `n` | keep-alive / latency (server answers `pong` with the same `n`) |
| `rematch` | | private duels only, after `end`: play again (see below) |
| `suggest` | | training mode only (section 5.4): ask Misaki for a placement; otherwise `error not_training` |

Puzzles, hints and answers use the **existing HTTP endpoints** with `match_id` + `match_token` (same
pattern as `run_id` / `run_token`; the pair comes from `start`, one token per player): `POST
/api/puzzle/next` (server picks deterministically from the match seed, §ranked-and-race 2), `GET
/api/puzzle/{id}/hint`, `POST /api/puzzle/{id}/answer`. When an answer for the player's current lock (or
tapped bug line) is checked, the server applies the outcome to that player's game and pushes the new
state over the socket. `kind` is `rescue` for locks and `debug` for bug lines.

- `POST /api/puzzle/next` in a match: `{kind: "rescue", match_id, match_token}` (`topic`/`tier`/`level`
  are ignored: the server uses the player's current lock, tier 3 for a boss lock, and the match level) or
  `{kind: "debug", bug: <bugLines[].id>, match_id, match_token}` (**contract addition**: `bug` names the
  tapped bug line; the server uses that line's `templateId`, tier 1. Without `bug`, the first bug line
  whose `templateId` equals the request's `template_id` is used). Asking again for a puzzle that is still
  open returns the same puzzle (no re-roll). `409` when there is nothing to solve (`rescue` needs `phase` `locked`; `debug` needs `phase` `play` and an existing bug line) or the match is over. A missing or invalid pair is ignored: the request works as a normal
  practice request and nothing is applied.
- The first puzzle of a lock spends a Debugger when owned (rule 11) and pushes a `state`. `exclude_*`
  fields are ignored; the server keeps its own history (last 500 ids, last 3 templates) per player, and
  `n` (the pick counter) is per player, so two players in the same situation get the same puzzle.
- `GET .../hint?level=n&match_id=&match_token=` records the highest hint level opened for that served
  puzzle; the answer is then paid per the usual hint factor.
- `POST .../answer` with the pair applies the result only when the puzzle was served to this player for
  their **current** lock part / bug line and has not been answered before (first answer counts). The
  response is the same as always; the effect arrives as `state` (+ `sent`, `incoming`). Answers without
  or with a wrong pair, for puzzles not served by the match, or for a lock that is gone are checked but
  not applied.

Server → client:

| `t` | Fields | Meaning |
| --- | --- | --- |
| `lobby` | `you: {nickname, rating}, opponent: {nickname, bot, connected, rating} \| null, level, starts_in` | waiting / countdown. `opponent` is `null` until paired; `rating` is the Elo (1000 for a new device) and `null` for the bot; `starts_in` is `null` or 3, 2, 1, 0 |
| `start` | `seed, level, match_id, match_token, at, elapsed` | 3-2-1 done, play. `at` = server Unix time of the start; `elapsed` = seconds since then (0, or more when re-sent on a reconnect: use it instead of `at` to avoid clock skew) |
| `state` | `you: {grid, tray, score, streak, items, pending, bugLines, lock, phase, status, bestStreak, sent, received, endReason, land_in, lock_in}`, `rev` | your full state after **every** change, including every change to your pending queue (incoming, cancel, landing, overtime, undo) (`rev` increases per player; `start`/new round restarts it). `land_in`: seconds until the timed landing (float, rounded to 0.1), `null` when nothing is pending; still reported while an open lock holds the timer (then it can be 0 or negative). `lock_in`: seconds left on the lock limit (float, 0.1), `null` without a lock. Seconds remaining, not absolute times: the state is pushed on changes only, so the client counts down locally between pushes |
| `opponent` | `{grid, score, pending, lock: bool, phase, connected}` | opponent's board, at most 4× per second; `pending` is a **number** of rows |
| `sent` | `lines, cancelled` | you sent / cancelled lines (for the animation); only when either is above 0 |
| `incoming` | `lines, from_topic, overtime?` | lines added to your pending queue (`overtime: true` for the overtime lines) |
| `landed` | `rows, timed?` | your pending lines just landed (not sent when the game ended). `timed: true` when the landing timer made them land (no placement of yours); absent after a placement. Sent just before the `state` that shows the landing |
| `lock_timeout` | | your lock ran out of time and became a bug line (rule 14); sent just before the `state` that shows it. A puzzle open for that lock is stale |
| `opponent_status` | `connected, grace_s` | opponent dropped (`grace_s` 20) / is back (0) |
| `end` | `winner: "you"\|"opponent"\|"draw", reason, you: {score, sent, received, locks}, opponent: {score, sent, received, locks, nickname, bot}, rating?: {before, after}` | match over (the last `opponent` and `state` are sent just before it) |
| `rematch_status` | `you, opponent, expired?` | private duels after `end`, see below |
| `error` | `code, message` | rejected action (e.g. illegal place: the client re-renders from the `state` that follows) |
| `coach` | `kind, text, cells?` | training mode only: Misaki's coaching (section 5.4) |
| `suggestion` | `i, r, c, cells, why` \| `none: true, why` | training mode only: the answer to `suggest` (section 5.4) |
| `pong` | `n` | |

`state.you` shapes (same as `game.js`): `grid` is 8×8 of `null` or `{topic, bug, bugId}`; `tray` has
`{id, shape, cells, w, h, topic}` or `null` for a used slot; `pending` is `[{topic, templateId}]` (oldest
first); `bugLines` is `[{id, cells: [[r, c]], topic, templateId}]` (`templateId` is never null: overtime rows
carry `<topic>_bug`); `lock` is `null` or `{rows, cols, cells, count, tier, boss, topic, debugger}` (`debugger`:
a Debugger was spent on it); `items` is `{bomb, shuffle, undo, debugger}`; `phase` is `play`, `locked` (the
lock's puzzle is the player's to solve; the server has no separate `puzzle` phase) or `over`; `status` is
`ok`/`warn`.

`error` codes: `bad_message`, `not_playing`, `illegal` (followed by a `state`), `no_rematch`, `replaced`,
`bad_ticket`, `queue_timeout`, `lobby_timeout`, `opponent_left`, `expired` (private code ran out), `not_training`
(`suggest` outside a training match),
`server_restart` (lobby only). Illegal actions never change the game.

The browser includes the cumulative `received` counter with each placement. If it differs from the server's
counter, an attack arrived while the move was in transit: the server rejects it with `error stale_state` followed
by a fresh `state`, leaving the board, tray and pending rows untouched. The player can review the incoming rows
before placing again. The counter includes overtime and never decreases when rows land or are cancelled.
Older clients that omit it keep the existing placement behavior; server-side bots do not use this guard.

**Rematch (private duels).** After `end` the sockets of a private duel stay open for 60 s and the server
sends `rematch_status {you: false, opponent: false}`. `{"t":"rematch"}` sets your flag and both players get
`rematch_status` (each from their own point of view). When both flagged within 60 s the server starts a new
match on the same sockets: fresh seed, new `match_id` / `match_token`, a new `start` + `state` straight away
(no countdown), rated as usual. A player who disconnects clears their flag. After 60 s:
`rematch_status {you: false, opponent: false, expired: true}` and the sockets are closed. Quick-match
rematch is a new search (the sockets are closed after `end`; `rematch` is `no_rematch` while playing).

`reason`: `nofit`, `topped_out` (old rule, no longer produced), `resign`, `disconnect`, `both_disconnected` (draw), `server_restart`.

## 4. Disconnects (UX)

- A dropped socket starts a **20-second grace**. The opponent sees an overlay "Đối thủ mất kết nối…
  15 s" and their own board keeps working. The dropped player's board is frozen (no pending lines land
  on it while away).
- Reconnecting with the same ticket within the grace resumes exactly: the server re-sends `start` (same
  `match_id` / `match_token`, `elapsed` > 0) and `state`, and tells the opponent `opponent_status
  connected: true`. This is also what a page reload does (the browser keeps the ticket in
  `sessionStorage`); in the lobby the server re-sends `lobby`. The browser reconnects automatically
  (backoff 0.5, 1, 2, 4 s) and shows "Đang kết nối lại…". A reconnect after the match ended gets `end`
  (and the socket is closed unless it is a private duel inside the rematch window).
- Grace expired → the dropped player loses (`reason: disconnect`). Both dropped → draw
  (`both_disconnected`: checked when the first grace runs out while the other is still gone). Lines the
  opponent sends keep queueing on a dropped player's board; nothing lands until they place again. Their landing
  timer and lock limit stand still while away (the deadlines move back by the time away).
- Closing the tab or tapping back = resign after a confirm dialog.
- A server restart (deploy) ends live matches with `server_restart` (winner `draw`); no rating change.
  uvicorn closes the sockets (close code 1012) before the app can send anything on a SIGTERM, so in
  practice the browser sees a closed socket and, on reconnect, `bad_ticket`: treat that as a restart. The
  deploy cron (`deploy/update.sh`) restarts the container when a new commit is pushed.

## 5. Misaki (the AI opponent)

Misaki is the game's AI character: the same name and avatar as the tutor ("Misaki · Gia sư AI"). As an
opponent she is a **search-based game AI** running server-side on the rules engine. What we say about
her must stay true: she plans moves with a search algorithm and an evaluation function; she is not
trained and does not learn; her puzzle answers are simulated at an accuracy set by her level (she does
not read the code). Always shown with an **AI** badge. Matches against Misaki never change the PvP rating.

### 5.1 Search
For each turn she considers the whole tray: every order of the (up to three) pieces and every legal
position, pruned with a beam (best `beam` candidates kept after each piece), and scores the resulting
board with:
- `+` lines completed (a lock she expects to clear: the board is simulated with the lock cleared and the
  reward, shaped like `SEND`, is weighted by her puzzle accuracy);
- `−` holes (empty cells with filled cells above them in the column) and covered empty cells (empty cells
  closed in on all four sides, where only a single block fits);
- `−` aggregate height and bumpiness (differences between adjacent column heights); heights are counted
  from the bottom because landing bug rows push blocks up;
- `−` blocks inside the **danger zone** (top `pending` rows), strongly;
- `−` boards where fewer of the next pieces fit (mobility: the share of the 13 shapes, weighted by how
  often they are dealt and over every rotation, that still fit somewhere; applied to the final candidates);
- `+` line progress (rows and columns without bug blocks that are nearly full), a small term added to the list
  above because completing lines is the only way a board clears.
The simulation uses the engine's rules, mirrored on 64-bit integers and checked against `rescue_engine`
in `tests/test_misaki.py`: a full row or column of normal blocks is a lock; the first placement of the plan
that makes no lock lands the pending rows (each block pushed above row 0 costs `W_LOST`). She plays the first placement of the best plan, then re-plans after every placement (the
opponent's lines may have landed). Measured: about 2-8 ms per decision at beam 32 on a typical mid-game
board (max about 15 ms in the benchmark; target < 50 ms). The weights were tuned by hand against simulated
matches; nothing is trained and nothing is remembered between matches.

### 5.2 Ladder
| Level | Name | Beam | Think delay per placement | Puzzle accuracy | Uses items |
| --- | --- | --- | --- | --- | --- |
| 1 | Misaki · Tập sự | 1 (greedy, one piece) | 2.0–3.0 s | 60% | no |
| 2 | Misaki · Khá | 4 | 1.4–2.2 s | 72% | bomb only |
| 3 | Misaki · Giỏi | 12 | 0.9–1.5 s | 84% | yes |
| 4 | Misaki · Bậc thầy | 32 | 0.5–1.0 s | 93% | yes |
Puzzle answers take 3–8 s (tier 1 3–5 s, tier 2 4–6.5 s, boss locks 5.5–8 s per puzzle, times 1.0 / 0.95 /
0.9 / 0.85 at levels 1–4, never outside 3–8 s), faster at higher levels; she never opens a hint. "Items" means
Bomb (used when the board is crowded or the plan is bad and a 3x3 blast clearly improves it) and Shuffle (only
when the best plan is very poor); a Debugger is spent automatically on her next lock as for any player; she
never uses Undo. Level 1 is always unlocked; beating level n (in a normal, non-training match) unlocks n+1,
stored per device in `ranked.sqlite` (table `misaki_progress`: games and wins per level; `unlocked` is derived:
1 + the highest level beaten, at most 4). A normal match counts as a game when it ends with a winner
(including a resignation or a disconnect, which are losses); draws (`both_disconnected`, `server_restart`)
and training matches count for nothing. A device's progress is forgotten after a year without a match.

Measured strength (`backend/tests/misaki_sim.py`, bot-vs-bot on the real match code with a virtual clock, seats
alternate): see section 7.

### 5.3 API
- `POST /api/pvp/bot {level, nickname, device_id, misaki: 1..4, training: bool}` → `{ticket}`.
  403 if `misaki` is not unlocked for that device (training too); 422 for `misaki` outside 1..4 or `training`
  without `misaki`. `training` defaults to false. Without `misaki` the generic "Máy" bot plays (section 3).
- `GET /api/pvp/misaki?device_id=` → `{unlocked: n, wins: {"1": k, ...}, games: {"1": k, ...}}` (all four levels
  listed; 422 for a bad device id).
- Lobby `opponent` for Misaki: `{nickname: "Misaki", bot: true, misaki: n, title: "Misaki · Giỏi", training: bool, plays_as: m, connected: true, rating: null}`.
  `misaki` and `title` are always the level the **player chose**; `plays_as` is the level she really plays at
  (equal to `misaki`, or one lower in training mode, never below 1). The nickname "Misaki" is only for the bot
  and is not a generated name (players still need generated names).
- `end` against Misaki adds `misaki: {level, unlocked_now: n | null}`: `level` is the level the player chose
  (in training too); `unlocked_now` is the level this win newly unlocked, `null` otherwise (a loss, a repeat
  win, level 4, any training match).

### 5.4 Training mode ("Luyện tập cùng Misaki")
Same match, but Misaki also coaches. Nothing in training mode is ranked or unlocks levels.
- Misaki plays one level lower than chosen (min 1) and her think delay per placement is ×1.5 (puzzle answer
  times are unchanged).
- Server → client `{"t":"coach", "kind": "<kind>", "text": "<Vietnamese or English, ≤ 120 chars>", "cells"?: [[r,c]...]}`
  (the language is the connection's `lang=en|vi` query parameter on the WebSocket URL; the variant is the same in both)
  pushed on events, at most one every 4 s (except `suggestion`). Kinds and when:
  `danger` (pending lines would push your blocks off, i.e. a block of yours is in the top `pending` rows: `n` is
  the number of pending rows and `cells` lists those blocks), `incoming` (first time the opponent sends lines;
  not for overtime lines), `cancel` (your clear cancelled pending lines), `streak` (streak 3),
  `wrong` (a wrong lock answer: nudges to tap the new bug line or use "Vì sao mình sai?"),
  `bugline` (you have an unfixed bug line for 30 s; once per bug line), `nofit_risk` (only one of your
  at-least-two tray pieces still fits), `good` (you completed 2+ lines at once). Texts come from
  `backend/content/misaki_coach.yaml` (several variants per kind, the k-th message of a kind uses
  `Random(f"{seed}:coach:{kind}:{k}")`, so a match tells the same story).
  Throttling: an event that arrives during the 4 s pause waits for it (the most important one, at most 6 s);
  `danger`, `nofit_risk` and `bugline` are never queued, they are looked at again about twice a second and
  after every change; `danger` repeats at most every 15 s, `nofit_risk` every 20 s, `incoming` is said once.
  Priority: wrong, danger, incoming, good, cancel, streak, nofit_risk, bugline.
- Client → server `{"t":"suggest"}` (at most once every 3 s of real time; a faster one is silently dropped):
  Misaki runs her level-4 search on **your** current state and answers
  `{"t":"suggestion", "i": tray index, "r", "c", "cells": [[r,c]...], "why": "<Vietnamese reason>"}`
  or `{"t":"suggestion", "none": true, "why": "..."}` (no piece fits, or a lock is open: nothing can be placed
  then). The placement is always legal on your current board. `why` comes from the `suggestion` copy by the
  dominant reason, in this order: `line` (it completes lines: `{n}` = how many), `danger` (lines are pending
  and the piece stays out of the rows they push up), `safe` (no new holes and the top two rows stay empty),
  otherwise `fit`. The UI outlines those cells on your board. Only in training mode; otherwise
  `error not_training`.

## 6. Rating

Quick-match and private matches between humans update an Elo rating per device (start 1000, K = 32),
stored in `ranked.sqlite` (table `pvp_ratings`, forgotten after a year without a match). Shown on the end
screen (`rating.before/after`) and in the PvP lobby. No public PvP leaderboard in this version. No rating
change for bot matches, `both_disconnected`, `server_restart`, or when both players share one device. Draws
count as 0.5.

## 7. Verification

- The golden harness (`backend/tests/js_harness/play.mjs`) gains `pvp` games: random garbage arrivals,
  cancels, landings, top-outs and overtime events are injected identically into the JS game and the
  Python engine; every final state must match.
- Match tests drive two WebSocket clients (and bot matches) through full games, disconnect/reconnect,
  grace expiry, resign, both-disconnect, illegal actions, and answers sent without/with wrong match
  token.
- Server limits: at most 200 live matches; one socket per ticket; messages ≤ 4 KB (a bigger frame closes
  the socket with code 1009); ≥ 10 messages per second per player are dropped silently; the outbox of a
  socket that does not read is capped (it is cut off and may reconnect).
- Overtime (rule 8) is on the server's match clock: events at 4:00, 4:20, ... (topic from
  `Random(f"{seed}:overtime:{k}")`, same for both players, template `<topic>_bug`).
- Misaki: `backend/tests/test_misaki.py` (bitboard mirrors of the engine rules, search legality, a decision-time
  benchmark with a generous CI bound, the ladder / unlock / 403 / `not_training` API, coach throttling and triggers,
  suggestion legality) and the strength check `backend/tests/misaki_sim.py`: full bot-vs-bot matches on the real
  match code (virtual clock, no sleeping), each level against the one below, seats alternating; the test requires
  at least 65% over 40 games per pair. `python -m tests.misaki_sim 200` prints the numbers (200 games per pair,
  seeds 1000..1199, with the timers of rules 4 and 14 on): Misaki 2 beats 1 in 60% (121/200), 3 beats 2 in 86%
  (172/200), 4 beats 3 in 96% (193/200), no draws; matches last about 1.5 to 2 minutes of match time.
- Timers (rules 4 and 14): `backend/tests/test_pvp_timers.py` (a match on a virtual clock: landing after 4 s, no
  extension, 2 s in overtime, held while a lock is open, lock limit 40 s / 70 s for a boss, late answer ignored, undo
  clears the deadline, `land_in` / `lock_in` in the state; plus the socket messages). The golden harness also feeds the
  events `{"t":"land"}` (timed landing: landing + no-fit check) and `{"t":"lock_timeout","parts":[...]}` (a lock
  resolved as a wrong answer, no Debugger spent) to `game.js` and to `replay_pvp`. `pvp_audit.py` checks every
  `timed_landing` trace like a placement landing. The other match tests run with the timers switched off
  (`pvp.LAND_DELAY_S` etc. set very high in their fixture).
- Match tests: `backend/tests/test_pvp_match.py` (HTTP + WebSocket, accelerated clock via `pvp.SPEED`);
  rules: `backend/tests/test_pvp_rules.py` (golden against `game.js`, 400 pvp games).
