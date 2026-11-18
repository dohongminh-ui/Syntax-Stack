// Plays random but legal Code Rescue games with the REAL frontend rules (frontend/js/game.js + pieces.js)
// and prints one JSON trace per game: the seed, the move list in the format of docs/ranked-and-race.md,
// the puzzle records a server would hold, and the final state. backend/tests/test_rescue_engine.py replays
// every trace with backend/app/rescue_engine.py and expects the same final state.
//
// Usage: node play.mjs [games=240] [seed0=1]
//
// The client flow below mirrors the Code Rescue controller in frontend/js/main.js (runLock, onBugTap,
// afterResolution, onBomb, onItem, doUndo). Puzzle answers and hint levels come from a fixed pseudo-random
// oracle (its own mulberry stream), so a trace is reproducible from (seed0, games).
import * as Game from '../../../frontend/js/game.js';

// Verbatim copy of mulberry() in frontend/js/main.js (that file needs a DOM, so it cannot be imported).
function mulberry(a) {
  return () => {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const LEVELS = ['beginner', 'intermediate', 'advanced'];
const LETTER = { variables: 'v', conditions: 'c', loops: 'l', functions: 'f' };

function gridRows(s) {
  return s.grid.map((row) => row.map((x) => (!x ? '.' : x.bug ? LETTER[x.topic].toUpperCase() : LETTER[x.topic])).join(''));
}

function trayView(s) {
  return s.tray.map((p) => (p ? { topic: p.topic, cells: p.cells.map((c) => [c[0], c[1]]) } : null));
}

function playGame(seed, level, index) {
  const s = Game.newGame({ mode: 'rescue', level, rng: mulberry(seed) });
  const ch = mulberry((seed ^ 0x5bd1e995) >>> 0); // the "player": choices and puzzle oracle
  const mix = Math.imul(index + 1, 2246822519) >>> 0; // spreads the per-game knobs independently of `level`
  const strategy = ['random', 'stacker', 'boss', 'clearer'][index % 4];
  const pCorrect = [0.62, 0.97, 0.9, 0.99][(mix >>> 3) % 4] - 0.05 * ch();
  const pHint = [0.02, 0.3, 0.6][(mix >>> 7) % 3]; // chance that a puzzle is answered after opening hints
  const maxMoves = 450 + Math.floor(ch() * 250);
  const quitChance = ch() < 0.3 ? 0.006 : 0;

  const moves = [];
  const records = [];
  const st = {
    boss: 0, bossFail: 0, bossFirstWrong: 0, locks: 0, lockFail: 0, bomb: 0, shuffle: 0, undo: 0, debugger: 0, bugfix: 0,
    bugfixWrong: 0, crash: 0, lastCommit: 0, lastCommitOk: 0, lastCommitFail: 0, nofit: 0, nofitSkip: 0,
    quit: 0, orphans: 0, hinted: 0, maxItem: 0,
  };
  let seq = 0;

  const hintOracle = () => {
    if (ch() >= pHint) return 0;
    const x = ch();
    return x < 0.4 ? 1 : x < 0.75 ? 2 : 3;
  };

  // The server's side of /api/puzzle/next + hints + answer, for one served puzzle.
  function serve({ kind, topic, tier, template = null }, { answered = true } = {}) {
    const id = `g${index}-${++seq}`;
    const rec = {
      id, seq, kind, req_topic: topic, req_tier: tier, req_template: template,
      topic, template_id: template || `${topic}_t${Math.floor(ch() * 4)}`,
      hint: hintOracle(), correct: answered ? ch() < pCorrect : null,
    };
    records.push(rec);
    Game.noteSeen(s, { id, template_id: rec.template_id });
    return rec;
  }
  const asPuzzle = (rec) => ({ id: rec.id, topic: rec.topic, template_id: rec.template_id, prompt: '' });

  function maybeOrphan(spec) {
    // a response that never reached the client: served and recorded, never used by a move
    if (ch() < 0.03) {
      serve(spec, { answered: ch() < 0.5 });
      st.orphans++;
    }
  }

  function end(reason) {
    moves.push({ t: 'end', reason });
    if (reason === 'crash') st.crash++;
    if (reason === 'nofit') st.nofit++;
    if (reason === 'quit') st.quit++;
  }

  // main.js afterResolution (rescue branch)
  function afterResolution() {
    while (s.phase !== 'over' && !Game.anyFit(s)) {
      if (s.lastCommitUsed) {
        Game.endGame(s, 'nofit');
        end('nofit');
        return;
      }
      if (ch() < 0.15) {
        Game.endGame(s, 'nofit');
        st.nofitSkip++;
        end('nofit');
        return;
      }
      s.lastCommitUsed = true;
      const topic = Game.lastCommitTopic(s);
      maybeOrphan({ kind: 'last_commit', topic, tier: 3 });
      const rec = serve({ kind: 'last_commit', topic, tier: 3 });
      moves.push({ t: 'last_commit', puzzle: rec.id });
      st.lastCommit++;
      if (!rec.correct) {
        Game.failLastCommit(s, { puzzle: asPuzzle(rec), response: {}, answer: null });
        st.lastCommitFail++;
        end('nofit');
        return;
      }
      st.lastCommitOk++;
      Game.clearCells(s, Game.cellsOfRows(s, Game.fullestRows(s)));
    }
  }

  // main.js runLock
  function runLock() {
    s.phase = 'puzzle';
    const L = s.lock;
    const useDbg = s.items.debugger > 0;
    if (useDbg) s.items.debugger--;
    const free = Game.freeHintLevel(s, useDbg);
    const parts = L.boss ? 2 : 1;
    const base = Game.baseFor(L);
    const tier = L.boss ? 3 : L.tier;
    let maxHint = 0;
    let failed = null;
    const used = [];
    if (L.boss) st.boss++;
    for (let i = 0; i < parts; i++) {
      maybeOrphan({ kind: 'rescue', topic: L.topic, tier });
      const rec = serve({ kind: 'rescue', topic: L.topic, tier });
      used.push(rec.id);
      maxHint = Math.max(maxHint, rec.hint);
      if (!rec.correct) {
        failed = rec;
        break;
      }
    }
    const move = { t: 'lock', puzzles: used };
    if (useDbg) {
      move.debugger = true;
      st.debugger++;
    }
    moves.push(move);
    if (!failed) {
      Game.applyCorrect(s, { base, maxHint, free, lines: L.count });
      Game.finishLock(s);
      st.locks++;
      if (maxHint > 0) st.hinted++;
      afterResolution();
    } else {
      st.lockFail++;
      if (L.boss) st.bossFail++;
      if (L.boss && used.length === 1) st.bossFirstWrong++; // the 2nd boss puzzle is never served
      const w = Game.applyWrong(s, { puzzle: asPuzzle(failed), response: {}, answer: null });
      if (w.result === 'crash') end('crash');
      else afterResolution();
    }
  }

  // main.js onBugTap
  function bugFix() {
    const bl = s.bugLines[Math.floor(ch() * s.bugLines.length)];
    maybeOrphan({ kind: 'debug', topic: bl.topic, tier: 1, template: bl.templateId });
    const rec = serve({ kind: 'debug', topic: bl.topic, tier: 1, template: bl.templateId });
    moves.push({ t: 'bugfix', bug: bl.id, puzzle: rec.id });
    if (rec.correct) {
      Game.fixBug(s, bl.id);
      st.bugfix++;
      afterResolution();
    } else {
      st.bugfixWrong++;
      const w = Game.applyDebugWrong(s, { puzzle: asPuzzle(rec), response: {}, answer: null });
      if (w.result === 'crash') end('crash');
    }
  }

  function tryBomb() {
    for (let k = 0; k < 6; k++) {
      const r = Math.floor(ch() * 8);
      const c = Math.floor(ch() * 8);
      if (Game.bomb(s, r, c)) {
        moves.push({ t: 'bomb', r, c });
        st.bomb++;
        return true;
      }
    }
    return false;
  }

  function legalMoves() {
    const out = [];
    s.tray.forEach((p, i) => {
      if (!p) return;
      for (let r = 0; r < 8; r++) for (let c = 0; c < 8; c++) if (Game.canPlace(s.grid, p, r, c)) out.push({ i, r, c, p });
    });
    return out;
  }

  // Placement strategies (all legal; they only differ in how they score the legal placements):
  //   random   uniform
  //   stacker  avoids completing small locks and keeps column 7 free
  //   clearer  plays like a person: completes lines, keeps pieces snug against walls and other pieces
  //   boss     packs the bottom 4 rows except column 7, then a vertical piece in column 7 locks 4 rows at once
  const snug = (mv) => {
    const own = new Set(mv.p.cells.map(([dr, dc]) => (mv.r + dr) * 8 + mv.c + dc));
    let n = 0;
    for (const [dr, dc] of mv.p.cells) {
      for (const [nr, nc] of [[-1, 0], [1, 0], [0, -1], [0, 1]]) {
        const rr = mv.r + dr + nr;
        const cc = mv.c + dc + nc;
        if (rr < 0 || rr > 7 || cc < 0 || cc > 7 || (!own.has(rr * 8 + cc) && s.grid[rr][cc])) n++;
      }
    }
    return n;
  };
  function scorePlacement(mv) {
    const { rows, cols } = Game.completedLines(s.grid, mv.p, mv.r, mv.c);
    const k = rows.length + cols.length;
    let score = ch();
    if (strategy === 'clearer') return score + 15 * k + 0.8 * snug(mv);
    if (k >= 4) score += 200;
    else if (k > 0) score -= 40;
    const inCol7 = mv.p.cells.filter(([, dc]) => mv.c + dc === 7).length;
    if (strategy === 'stacker') return k < 4 ? score - 10 * inCol7 : score;
    // boss
    for (const [dr, dc] of mv.p.cells) {
      const inside = mv.r + dr >= 4 && mv.c + dc <= 6;
      score += inside ? 3 + 0.3 * (mv.r + dr) - 0.2 * (mv.c + dc) : -8;
    }
    return score + 0.8 * snug(mv);
  }
  function pickPlacement(list) {
    if (strategy === 'random') return list[Math.floor(ch() * list.length)];
    let best = null;
    let bestScore = -Infinity;
    for (const mv of list) {
      const score = scorePlacement(mv);
      if (score > bestScore) {
        bestScore = score;
        best = mv;
      }
    }
    return best;
  }

  for (;;) {
    if (s.phase === 'over') break;
    if (moves.length >= maxMoves || ch() < quitChance) {
      Game.endGame(s, 'quit');
      end('quit');
      break;
    }
    if (s.phase === 'locked') {
      if (s.items.undo > 0 && s.snapshot && ch() < 0.6) {
        Game.undo(s);
        moves.push({ t: 'undo' });
        st.undo++;
        continue;
      }
      runLock();
      continue;
    }
    // phase 'play'
    if (s.items.bomb > 0 && ch() < 0.4 && tryBomb()) {
      afterResolution();
      continue;
    }
    if (s.items.shuffle > 0 && ch() < 0.3 && Game.shuffle(s)) {
      moves.push({ t: 'shuffle' });
      st.shuffle++;
      afterResolution();
      continue;
    }
    if (s.bugLines.length && ch() < 0.35) {
      bugFix();
      continue;
    }
    const mv = pickPlacement(legalMoves());
    const res = Game.place(s, mv.i, mv.r, mv.c);
    moves.push({ t: 'place', i: mv.i, r: mv.r, c: mv.c });
    if (res.lock) s.phase = 'locked';
    else afterResolution();
    st.maxItem = Math.max(st.maxItem, s.items.bomb, s.items.shuffle, s.items.undo, s.items.debugger);
  }

  return {
    seed, level, strategy, moves, records, stats: st,
    final: {
      score: s.score,
      locks: st.locks,
      mistakes: s.wrongLog.length,
      bugs_fixed: s.bugsFixed,
      best_streak: s.bestStreak,
      streak: s.streak,
      status: s.status,
      end_reason: s.endReason,
      last_commit_used: s.lastCommitUsed,
      grid: gridRows(s),
      items: { ...s.items },
      tray: trayView(s),
    },
  };
}

const games = Number(process.argv[2] || 240);
const seed0 = Number(process.argv[3] || 1);
const out = [];
for (let i = 0; i < games; i++) {
  const seed = Math.imul(i + seed0, 2654435761) >>> 0; // spread over the full unsigned 32-bit range
  out.push(playGame(seed, LEVELS[Math.floor(i / 4) % 3], i));
}
process.stdout.write(JSON.stringify(out));
