// Syntax Rows: pure state and rules. No DOM, no network.
// A level (from the API) is { id, order, title, goal, expected_output, rows, cols, indent_cols, tokens: [{id, text, w, topic}] }.
export const DEFAULT_INDENT_COLS = 2;
export const STAR_BASE = 300;
export const DISTRACTOR_BONUS = 50;

export function newState(level) {
  return {
    level,
    placed: {}, // tokenId -> { row, col }
    runs: 0,
    hintsMax: 0, // highest hint level ever opened (drives stars)
    ctxGroup: null, // error group the visible hints belong to
    hintsShown: [], // hint texts for the current context
    lastGroup: null,
    errorRow: null,
    passed: false,
    result: null,
  };
}

const indentCols = (lv) => lv.indent_cols ?? DEFAULT_INDENT_COLS;
export const tokenOf = (s, id) => s.level.tokens.find((t) => t.id === id);

export function rowTokens(s, row, ignoreId = null) {
  return Object.entries(s.placed)
    .filter(([id, p]) => p.row === row && id !== ignoreId)
    .map(([id, p]) => ({ id, col: p.col, w: tokenOf(s, id).w, text: tokenOf(s, id).text }))
    .sort((a, b) => a.col - b.col);
}

/** Can token `id` sit with its left edge at (row, col)? Ignores the token's own current position. */
export function canPlace(s, id, row, col) {
  const t = tokenOf(s, id);
  const { rows, cols } = s.level;
  if (!t || row < 0 || row >= rows || col < 0 || col + t.w > cols) return false;
  const others = rowTokens(s, row, id);
  if (others.some((o) => col < o.col + o.w && o.col < col + t.w)) return false;
  const first = Math.min(col, ...others.map((o) => o.col));
  return first <= indentCols(s.level); // a row may not start further right than the last indent column
}

/** Nearest valid column to `col` within `maxDist`, or null. Makes taps and drops forgiving. */
export function fitCol(s, id, row, col, maxDist = Infinity) {
  const t = tokenOf(s, id);
  if (!t) return null;
  const hi = s.level.cols - t.w;
  const want = Math.max(0, Math.min(hi, col));
  for (let d = 0; d <= Math.min(maxDist, s.level.cols); d++) {
    for (const c of d === 0 ? [want] : [want - d, want + d]) if (c >= 0 && c <= hi && canPlace(s, id, row, c)) return c;
  }
  return null;
}

export function place(s, id, row, col) {
  if (!canPlace(s, id, row, col)) return false;
  s.placed[id] = { row, col };
  return true;
}

export function remove(s, id) {
  delete s.placed[id];
}

export const unplaced = (s) => s.level.tokens.filter((t) => !s.placed[t.id]);

/** Program lines as the server will assemble them: one entry per non-empty row. */
export function lines(s) {
  const out = [];
  for (let r = 0; r < s.level.rows; r++) {
    const toks = rowTokens(s, r);
    if (!toks.length) continue;
    const indent = Math.min(toks[0].col, indentCols(s.level));
    out.push({ row: r, indent, text: toks.map((t) => t.text).join(' '), ids: toks.map((t) => t.id) });
  }
  return out;
}

/** Preview lines for every board row (empty rows stay as blank lines so numbers match the gutter). */
export function previewLines(s) {
  const byRow = new Map(lines(s).map((l) => [l.row, l]));
  return Array.from({ length: s.level.rows }, (_, r) => {
    const l = byRow.get(r);
    return { n: r + 1, text: l ? '    '.repeat(l.indent) + l.text : '', row: r };
  });
}

export function payload(s) {
  const rows = [];
  for (let r = 0; r < s.level.rows; r++) {
    const toks = rowTokens(s, r);
    if (toks.length) rows.push({ row: r, tokens: toks.map((t) => ({ id: t.id, col: t.col })) });
  }
  return { rows };
}

/** Client-side guard for what the server would answer with 422 / bad indent. Returns null when fine. */
export function localCheck(s) {
  for (let r = 0; r < s.level.rows; r++) {
    const toks = rowTokens(s, r);
    if (toks.length && toks[0].col > indentCols(s.level)) {
      return { row: r, error_group: 'bad_indent', message: `Hàng ${r + 1}: mảnh đầu tiên phải nằm ở một trong ${indentCols(s.level) + 1} cột đầu (cột thụt lề).` };
    }
  }
  return null;
}

/** Spec §6. runs includes the passing run. */
export function starsFor(runs, hintsMax) {
  if (runs <= 1 && hintsMax === 0) return 3;
  if (runs <= 3 && hintsMax <= 1) return 2;
  return 1;
}

export function scoreFor(stars, unusedDistractors) {
  return Math.round((STAR_BASE * stars) / 3) + DISTRACTOR_BONUS * (unusedDistractors || 0);
}

export function recordRun(s) {
  s.runs++;
}

/** Hints belong to the error group of the latest run. A new group restarts the visible hint list. */
export function setHintContext(s, group) {
  if (s.ctxGroup === group) return;
  s.ctxGroup = group;
  s.hintsShown = [];
}

export function addHint(s, hint) {
  s.hintsShown.push(hint);
  s.hintsMax = Math.max(s.hintsMax, s.hintsShown.length);
}

export const GROUP_LABEL = {
  wrong_order: 'Sai thứ tự',
  bad_indent: 'Sai thụt lề',
  syntax: 'Sai cú pháp',
  missing_colon: 'Thiếu dấu hai chấm',
  output_mismatch: 'Đầu ra không khớp',
  missing_construct: 'Thiếu cấu trúc bắt buộc',
  empty: 'Chưa có mã',
};

// ---- progress helpers (levels come from the API list, progress from storage) ------------------
export function isUnlocked(levels, progress, id) {
  const i = levels.findIndex((l) => l.id === id);
  if (i <= 0) return i === 0;
  return (progress[levels[i - 1].id]?.stars || 0) >= 1;
}

export function totals(levels, progress) {
  let stars = 0;
  let score = 0;
  let done = 0;
  for (const l of levels) {
    const p = progress[l.id];
    if (p?.stars) {
      stars += p.stars;
      score += p.score || 0;
      done++;
    }
  }
  return { stars, score, done, max: levels.length * 3 };
}
