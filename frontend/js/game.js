// Pure game state and rules. No DOM, no network.
import { TOPICS, makePiece } from './pieces.js';

export const SIZE = 8;
export const BASE_POINTS = [0, 100, 250, 450, 700]; // index = number of lines (4 = 4+)
export const HINT_FACTOR = [1, 0.9, 0.75, 0.5];
export const HINT_PENALTY_PCT = [0, 10, 25, 50];
export const BUG_FIX_POINTS = 150;
export const PRACTICE_BUG_LIFETIME = 5;
const ITEM_CAP = 3;

export function streakFactor(n) {
  if (n >= 5) return 2;
  if (n >= 3) return 1.5;
  if (n === 2) return 1.2;
  return 1;
}

const emptyGrid = () => Array.from({ length: SIZE }, () => Array(SIZE).fill(null));
const cloneGrid = (g) => g.map((row) => row.map((c) => (c ? { ...c } : null)));

export function newGame({ mode = 'rescue', level = 'beginner', focusTopic = null, rng = Math.random } = {}) {
  const s = {
    mode,
    level,
    focusTopic,
    rng,
    grid: emptyGrid(),
    tray: [],
    score: 0,
    streak: 0,
    bestStreak: 0,
    mistakes: 0, // rescue: 0 = stable, 1 = warning
    status: 'ok', // ok | warn | crash
    items: { bomb: 0, shuffle: 0, undo: 0, debugger: 0 },
    bugsFixed: 0,
    lastCommitUsed: false,
    seenIds: [],
    recentTemplates: [],
    wrongLog: [],
    topicMisses: {},
    bugLines: [],
    nextBugId: 1,
    placements: 0,
    phase: 'play', // play | locked | puzzle | over
    lock: null,
    snapshot: null,
    endReason: null,
  };
  refillTray(s);
  return s;
}

export function pieceWeights(s) {
  if (s.focusTopic) {
    const w = {};
    for (const t of TOPICS) w[t] = t === s.focusTopic ? 0.7 : 0.1;
    return w;
  }
  if (s.mode === 'practice') {
    const w = {};
    for (const t of TOPICS) w[t] = 1 + (s.topicMisses[t] || 0);
    return w;
  }
  return null;
}

export function refillTray(s) {
  const w = pieceWeights(s);
  s.tray = [0, 1, 2].map(() => makePiece(s.rng, w));
}

export function canPlace(grid, piece, r, c) {
  return piece.cells.every(([dr, dc]) => {
    const rr = r + dr;
    const cc = c + dc;
    return rr >= 0 && rr < SIZE && cc >= 0 && cc < SIZE && !grid[rr][cc];
  });
}

export function fitsAnywhere(grid, piece) {
  for (let r = 0; r < SIZE; r++) for (let c = 0; c < SIZE; c++) if (canPlace(grid, piece, r, c)) return true;
  return false;
}

export function anyFit(s) {
  return s.tray.some((p) => p && fitsAnywhere(s.grid, p));
}

function snapshot(s) {
  return {
    grid: cloneGrid(s.grid),
    tray: s.tray.slice(),
    score: s.score,
    placements: s.placements,
    bugLines: s.bugLines.map((b) => ({ ...b })),
  };
}

// Place tray piece idx with its top-left cell at (r, c). Returns null if invalid.
export function place(s, idx, r, c) {
  const piece = s.tray[idx];
  if (!piece || !canPlace(s.grid, piece, r, c)) return null;
  s.snapshot = snapshot(s);
  const placed = [];
  for (const [dr, dc] of piece.cells) {
    s.grid[r + dr][c + dc] = { topic: piece.topic, bug: false, bugId: null };
    placed.push([r + dr, c + dc]);
  }
  s.score += piece.cells.length;
  s.tray[idx] = null;
  s.placements++;
  const expired = tickBugLines(s);
  if (s.tray.every((p) => !p)) refillTray(s);
  const lock = findLock(s);
  s.lock = lock;
  return { placed, lock, expired };
}

// Practice: bug lines vanish after 5 placements.
function tickBugLines(s) {
  if (s.mode !== 'practice') return [];
  const expired = [];
  for (const b of s.bugLines) b.placementsLeft--;
  for (const b of s.bugLines.filter((x) => x.placementsLeft <= 0)) {
    for (const [r, c] of b.cells) {
      s.grid[r][c] = null;
      expired.push([r, c]);
    }
  }
  s.bugLines = s.bugLines.filter((x) => x.placementsLeft > 0);
  refreshStatus(s);
  return expired;
}

export function findLock(s) {
  const rows = [];
  const cols = [];
  for (let r = 0; r < SIZE; r++) {
    if (s.grid[r].every((x) => x && !x.bug)) rows.push(r);
  }
  for (let c = 0; c < SIZE; c++) {
    let ok = true;
    for (let r = 0; r < SIZE; r++) if (!s.grid[r][c] || s.grid[r][c].bug) ok = false;
    if (ok) cols.push(c);
  }
  if (!rows.length && !cols.length) return null;
  const set = new Set();
  for (const r of rows) for (let c = 0; c < SIZE; c++) set.add(r * SIZE + c);
  for (const c of cols) for (let r = 0; r < SIZE; r++) set.add(r * SIZE + c);
  const cells = [...set].sort((a, b) => a - b).map((k) => [Math.floor(k / SIZE), k % SIZE]);
  const count = rows.length + cols.length;
  return {
    rows,
    cols,
    cells,
    count,
    tier: Math.min(count, 3),
    boss: count >= 4,
    topic: majorityTopic(s, cells),
  };
}

export function majorityTopic(s, cells) {
  const n = {};
  for (const [r, c] of cells) n[s.grid[r][c].topic] = (n[s.grid[r][c].topic] || 0) + 1;
  const max = Math.max(...Object.values(n));
  const tied = Object.keys(n).filter((t) => n[t] === max);
  return tied[Math.floor(s.rng() * tied.length)];
}

export function baseFor(lock) {
  return BASE_POINTS[Math.min(lock.count, 4)];
}

// Highest hint level that is free for this player/puzzle.
export function freeHintLevel(s, debuggerActive) {
  return Math.max(s.level === 'beginner' ? 1 : 0, debuggerActive ? 2 : 0);
}

export function penaltyLevel(maxViewed, free) {
  return maxViewed <= free ? 0 : maxViewed;
}

export function reward(s, { base, maxHint, free }) {
  const pl = penaltyLevel(maxHint, free);
  const clean = pl === 0;
  const newStreak = clean ? s.streak + 1 : 1;
  const points = Math.round(base * HINT_FACTOR[pl] * streakFactor(newStreak));
  return { points, clean, penaltyLevel: pl };
}

export function noteSeen(s, puzzle) {
  s.seenIds.push(puzzle.id);
  s.recentTemplates.push(puzzle.template_id);
  if (s.recentTemplates.length > 3) s.recentTemplates.shift();
}

function addItem(s, name, list, label) {
  if (s.items[name] < ITEM_CAP) {
    s.items[name]++;
    list.push(label);
  }
}

export function applyCorrect(s, { base, maxHint, free, lines }) {
  const r = reward(s, { base, maxHint, free });
  s.score += r.points;
  const newItems = [];
  if (r.clean) {
    s.streak++;
    if (s.streak === 3) addItem(s, 'bomb', newItems, 'Bom');
    if (s.streak === 5) addItem(s, 'shuffle', newItems, 'Xáo khối');
  } else {
    s.streak = 0;
  }
  if (lines >= 4) addItem(s, 'undo', newItems, 'Hoàn tác');
  s.bestStreak = Math.max(s.bestStreak, s.streak);
  return { ...r, newItems };
}

export function finishLock(s) {
  if (s.lock) for (const [r, c] of s.lock.cells) s.grid[r][c] = null;
  s.lock = null;
  s.snapshot = null;
  s.phase = 'play';
}

export function refreshStatus(s) {
  if (s.endReason === 'crash') s.status = 'crash';
  else if (s.mode === 'rescue') s.status = s.mistakes > 0 ? 'warn' : 'ok';
  else s.status = s.bugLines.length ? 'warn' : 'ok';
}

function logWrong(s, puzzle, response, kind) {
  s.streak = 0;
  s.topicMisses[puzzle.topic] = (s.topicMisses[puzzle.topic] || 0) + 1;
  s.wrongLog.push({
    puzzleId: puzzle.id,
    topic: puzzle.topic,
    templateId: puzzle.template_id,
    prompt: puzzle.prompt,
    explanation: response?.explanation || '',
    solution: response?.solution_code || '',
    kind,
  });
}

// Wrong rescue answer. Returns {result: 'bug' | 'crash'}.
export function applyWrong(s, { puzzle, response }) {
  logWrong(s, puzzle, response, 'rescue');
  if (s.mode === 'rescue' && s.mistakes >= 1) {
    s.endReason = 'crash';
    s.phase = 'over';
    refreshStatus(s);
    return { result: 'crash' };
  }
  const id = s.nextBugId++;
  const cells = s.lock.cells.map((x) => x.slice());
  for (const [r, c] of cells) s.grid[r][c].bug = true, (s.grid[r][c].bugId = id);
  s.bugLines.push({
    id,
    cells,
    topic: puzzle.topic,
    templateId: puzzle.template_id,
    placementsLeft: PRACTICE_BUG_LIFETIME,
  });
  if (s.mode === 'rescue') s.mistakes = 1;
  s.lock = null;
  s.snapshot = null;
  s.phase = 'play';
  refreshStatus(s);
  return { result: 'bug' };
}

// Wrong Debug answer: rescue = crash, practice = bug line stays.
export function applyDebugWrong(s, { puzzle, response }) {
  logWrong(s, puzzle, response, 'debug');
  if (s.mode === 'rescue') {
    s.endReason = 'crash';
    s.phase = 'over';
    refreshStatus(s);
    return { result: 'crash' };
  }
  return { result: 'stay' };
}

export function fixBug(s, bugId) {
  const b = s.bugLines.find((x) => x.id === bugId);
  if (!b) return null;
  for (const [r, c] of b.cells) s.grid[r][c] = null;
  s.bugLines = s.bugLines.filter((x) => x.id !== bugId);
  s.score += BUG_FIX_POINTS;
  s.bugsFixed++;
  s.mistakes = 0;
  const newItems = [];
  addItem(s, 'debugger', newItems, 'Debugger');
  refreshStatus(s);
  return { points: BUG_FIX_POINTS, newItems, cells: b.cells };
}

export function lastCommitTopic(s) {
  const entries = Object.entries(s.topicMisses).filter(([, n]) => n > 0);
  if (!entries.length) return TOPICS[Math.floor(s.rng() * TOPICS.length)];
  const max = Math.max(...entries.map((e) => e[1]));
  const top = entries.filter((e) => e[1] === max).map((e) => e[0]);
  return top[Math.floor(s.rng() * top.length)];
}

export function failLastCommit(s, { puzzle, response }) {
  logWrong(s, puzzle, response, 'last_commit');
  s.endReason = 'nofit';
  s.phase = 'over';
}

// Rows (without bug cells) sorted by how full they are. Used by Last Commit and practice.
export function fullestRows(s, n = 3) {
  const rows = [];
  for (let r = 0; r < SIZE; r++) {
    if (s.grid[r].some((x) => x && x.bug)) continue;
    const filled = s.grid[r].filter(Boolean).length;
    if (filled > 0) rows.push({ r, filled });
  }
  rows.sort((a, b) => b.filled - a.filled || a.r - b.r);
  return rows.slice(0, n).map((x) => x.r);
}

export function cellsOfRows(s, rows) {
  const cells = [];
  for (const r of rows) for (let c = 0; c < SIZE; c++) if (s.grid[r][c]) cells.push([r, c]);
  return cells;
}

export function clearCells(s, cells) {
  for (const [r, c] of cells) s.grid[r][c] = null;
}

// Practice fallback when even clearing rows does not make a piece fit.
export function clearEverything(s) {
  s.grid = emptyGrid();
  s.bugLines = [];
  refreshStatus(s);
}

// Bomb: 3x3 around (r, c), bug cells survive, no points. Returns cleared cells or null.
export function bomb(s, r, c) {
  if (s.items.bomb < 1) return null;
  const cleared = [];
  for (let dr = -1; dr <= 1; dr++)
    for (let dc = -1; dc <= 1; dc++) {
      const rr = r + dr;
      const cc = c + dc;
      if (rr < 0 || rr >= SIZE || cc < 0 || cc >= SIZE) continue;
      const cell = s.grid[rr][cc];
      if (cell && !cell.bug) cleared.push([rr, cc]);
    }
  if (!cleared.length) return null;
  s.items.bomb--;
  clearCells(s, cleared);
  return cleared;
}

export function shuffle(s) {
  if (s.items.shuffle < 1) return false;
  s.items.shuffle--;
  refillTray(s);
  return true;
}

export function canUndo(s) {
  return s.items.undo > 0 && !!s.snapshot;
}

export function undo(s) {
  if (!canUndo(s)) return false;
  const sn = s.snapshot;
  s.grid = sn.grid;
  s.tray = sn.tray;
  s.score = sn.score;
  s.placements = sn.placements;
  s.bugLines = sn.bugLines;
  s.items.undo--;
  s.lock = null;
  s.snapshot = null;
  s.phase = 'play';
  refreshStatus(s);
  return true;
}

export function endGame(s, reason) {
  s.phase = 'over';
  s.endReason = reason;
  refreshStatus(s);
}
