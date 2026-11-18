// Move log of a ranked / race run. The server replays these moves with the same rules and computes the
// score itself, so this file is the single place that decides what is sent. See docs/ranked-and-race.md section 3.
//
// Every function is a no-op while no run is active, so the hooks in main.js stay one-liners:
//   place     main.js onPlace      after Game.place succeeded
//   lock      main.js runLock      after the lock's puzzle(s) were answered, right before the result is applied
//   undo      main.js doUndo       after Game.undo succeeded
//   bomb      main.js onBomb       after Game.bomb cleared cells
//   shuffle   main.js onItem       after Game.shuffle succeeded
//   bugfix    main.js onBugTap     after the debug puzzle was answered, right before the result is applied
//   lastCommit main.js afterResolution after the Last Commit puzzle was answered, right before the result is applied
//   end       main.js finish       when the game ends (crash | nofit | quit)
// Puzzle outcomes (correct / wrong / hints) are NOT in the log: the server records them from the API calls.

const MAX_MOVES = 3000; // server limit

let run = null; // { id, token, kind, level, seed, race? }
let log = [];
let ended = false;

export function start(r) {
  run = r || null;
  log = [];
  ended = false;
}

export function clear() {
  run = null;
  log = [];
  ended = false;
}

export const active = () => !!run && !ended;
export const current = () => run;
export const moves = () => log.slice();

function push(move) {
  if (!run || ended) return;
  if (log.length >= MAX_MOVES - 1 && move.t !== 'end') return; // keep room for the final move
  log.push(move);
}

export const place = (i, r, c) => push({ t: 'place', i, r, c });

/** `puzzles` = ids served for this lock (1, or 2 for a boss lock; fewer if the first boss puzzle was wrong). */
export function lock(puzzles, usedDebugger) {
  const m = { t: 'lock', puzzles: puzzles.slice() };
  if (usedDebugger) m.debugger = true;
  push(m);
}

export const undo = () => push({ t: 'undo' });
export const bomb = (r, c) => push({ t: 'bomb', r, c });
export const shuffle = () => push({ t: 'shuffle' });
export const bugfix = (bug, puzzle) => push({ t: 'bugfix', bug, puzzle });
export const lastCommit = (puzzle) => push({ t: 'last_commit', puzzle });

export function end(reason) {
  if (!run || ended) return;
  push({ t: 'end', reason });
  ended = true;
}
