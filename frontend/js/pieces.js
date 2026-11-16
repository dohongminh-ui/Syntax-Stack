// Piece shapes and random piece generation. No DOM.
export const TOPICS = ['variables', 'conditions', 'loops', 'functions'];
export const TOPIC_NAMES = {
  variables: 'Biến',
  conditions: 'Điều kiện',
  loops: 'Vòng lặp',
  functions: 'Hàm',
};
export const TOPIC_GLYPH = { variables: 'x=', conditions: 'if', loops: 'for', functions: 'f()' };

// Base shapes as [row, col]. Rotations are generated on pick.
const BASE = {
  dot: { cells: [[0, 0]], w: 1 },
  i2: { cells: [[0, 0], [0, 1]], w: 3 },
  i3: { cells: [[0, 0], [0, 1], [0, 2]], w: 3 },
  i4: { cells: [[0, 0], [0, 1], [0, 2], [0, 3]], w: 2 },
  i5: { cells: [[0, 0], [0, 1], [0, 2], [0, 3], [0, 4]], w: 1 },
  sq2: { cells: [[0, 0], [0, 1], [1, 0], [1, 1]], w: 2 },
  sq3: { cells: [[0, 0], [0, 1], [0, 2], [1, 0], [1, 1], [1, 2], [2, 0], [2, 1], [2, 2]], w: 0.6 },
  l3: { cells: [[0, 0], [1, 0], [1, 1]], w: 3 },
  l4: { cells: [[0, 0], [1, 0], [2, 0], [2, 1]], w: 2 },
  j4: { cells: [[0, 1], [1, 1], [2, 1], [2, 0]], w: 2 },
  t: { cells: [[0, 0], [0, 1], [0, 2], [1, 1]], w: 2 },
  s: { cells: [[0, 1], [0, 2], [1, 0], [1, 1]], w: 1.5 },
  z: { cells: [[0, 0], [0, 1], [1, 1], [1, 2]], w: 1.5 },
};

export function normalize(cells) {
  const minR = Math.min(...cells.map((c) => c[0]));
  const minC = Math.min(...cells.map((c) => c[1]));
  return cells
    .map(([r, c]) => [r - minR, c - minC])
    .sort((a, b) => a[0] - b[0] || a[1] - b[1]);
}

export function rotate(cells) {
  return normalize(cells.map(([r, c]) => [c, -r]));
}

let uid = 1;

function pickWeighted(items, weightOf, rng) {
  const total = items.reduce((s, it) => s + weightOf(it), 0);
  let x = rng() * total;
  for (const it of items) {
    x -= weightOf(it);
    if (x <= 0) return it;
  }
  return items[items.length - 1];
}

export function pickTopic(rng, weights) {
  if (!weights) return TOPICS[Math.floor(rng() * TOPICS.length)];
  return pickWeighted(TOPICS, (t) => weights[t] ?? 1, rng);
}

export function makePiece(rng = Math.random, weights = null) {
  const key = pickWeighted(Object.keys(BASE), (k) => BASE[k].w, rng);
  let cells = normalize(BASE[key].cells);
  const turns = Math.floor(rng() * 4);
  for (let i = 0; i < turns; i++) cells = rotate(cells);
  const h = Math.max(...cells.map((c) => c[0])) + 1;
  const w = Math.max(...cells.map((c) => c[1])) + 1;
  return { id: 'p' + uid++, shape: key, cells, w, h, topic: pickTopic(rng, weights) };
}
