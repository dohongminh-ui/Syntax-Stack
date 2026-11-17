// Start screen: keycap title (with the one-time press wave) and the two live mini previews.
import { el, anim, EASE } from './ui.js';
import { keycap } from './keycap.js';
import { TOPICS, TOPIC_GLYPH } from './pieces.js';

const ROWS = ['SYNTAX', 'STACK'];
let waved = false;

function shuffled(a) {
  const x = a.slice();
  for (let i = x.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [x[i], x[j]] = [x[j], x[i]];
  }
  return x;
}

export function buildTitle() {
  const total = ROWS.join('').length;
  const picks = shuffled([...Array(total).keys()]).slice(0, TOPICS.length);
  const topicAt = new Map(picks.map((idx, i) => [idx, TOPICS[i]]));
  let n = 0;
  const keys = [];
  ROWS.forEach((word, ri) => {
    const row = document.getElementById('tk-' + (ri + 1));
    row.textContent = '';
    for (const ch of word) {
      const k = keycap({ topic: topicAt.get(n) || 'neutral', legend: ch, legendClass: 'legend legend-c' });
      row.append(k);
      keys.push(k);
      n++;
    }
  });
  return keys;
}

/** Keys press in a left-to-right wave: rare, once per visit (delight allowed). */
export function playWave(keys) {
  if (waved) return;
  waved = true;
  try {
    if (sessionStorage.getItem('ss.wave')) return;
    sessionStorage.setItem('ss.wave', '1');
  } catch {
    /* storage blocked: still play once per page load */
  }
  keys.forEach((k, i) => {
    anim(k.firstElementChild, [{ transform: 'translateY(0)' }, { transform: 'translateY(3px)', offset: 0.35 }, { transform: 'translateY(0)' }], { duration: 300, delay: 250 + i * 70, easing: EASE.out });
    anim(k, [{ transform: 'translateY(0)' }, { transform: 'translateY(-3px)', offset: 0.7 }, { transform: 'translateY(0)' }], { duration: 300, delay: 250 + i * 70, easing: EASE.out });
  });
}

// ---- home backdrop: desk-lamp spotlight, socket grid, drifting code keycaps ------------------------------------
// Hand-placed along the edges (x/y in % of the viewport) so nothing sits behind the title or the cards.
// depth: 'near' = larger, clearer, faster; 'far' = smaller, dimmer, blurred. Hidden on phones (game.css).
const DRIFT = [
  { t: 'for', topic: 'loops', x: 6, y: 16, d: 'near' },
  { t: 'x =', topic: 'variables', x: 93, y: 12, d: 'far' },
  { t: 'def', topic: 'functions', x: 5, y: 36, d: 'far' },
  { t: 'print()', topic: 'functions', x: 94, y: 40, d: 'near' },
  { t: 'if', topic: 'conditions', x: 4, y: 58, d: 'far' },
  { t: 'while', topic: 'loops', x: 95, y: 62, d: 'far' },
  { t: 'i', topic: 'variables', x: 7, y: 80, d: 'near' },
  { t: ':', topic: 'neutral', x: 94, y: 84, d: 'near' },
  { t: 'range(3)', topic: 'loops', x: 5, y: 94, d: 'far' },
  { t: 'return', topic: 'functions', x: 93, y: 95, d: 'far' },
];

export function buildBackdrop() {
  if (document.querySelector('.home-bg')) return;
  const bg = el('div', { class: 'home-bg', 'aria-hidden': 'true' });
  DRIFT.forEach((p, i) => {
    const k = keycap({ topic: p.topic, legend: p.t, legendClass: 'legend legend-c', cls: 'home-tok ' + p.d });
    const near = p.d === 'near';
    const sign = i % 2 ? 1 : -1;
    Object.assign(k.style, { left: p.x + '%', top: p.y + '%' });
    k.style.setProperty('--dur', (near ? 22 : 30) + (i % 3) * 4 + 's');
    k.style.setProperty('--delay', -(i * 3.7) + 's');
    k.style.setProperty('--dx', sign * (near ? 10 : 6) + 'px');
    k.style.setProperty('--dy', (near ? -22 : -14) + 'px');
    k.style.setProperty('--r0', sign * -4 + 'deg');
    k.style.setProperty('--r1', sign * 3 + 'deg');
    bg.append(k);
  });
  document.body.append(bg);
}

// ---- previews ------------------------------------------------------------------------------------------------
export function buildPreviews() {
  // Code Rescue: 4x4 mini plate with a few caps
  const map = { v: 'variables', c: 'conditions', l: 'loops', f: 'functions' };
  const pattern = ['.vv.', 'cvvl', 'cc.l', 'f.ll'];
  const grid = el('div', { class: 'mp-grid' });
  for (const rowStr of pattern) {
    for (const ch of rowStr) {
      const cell = el('div', { class: 'cell' + (ch === '.' ? ' empty' : '') });
      const t = map[ch] || 'neutral';
      cell.append(keycap({ topic: t, legend: map[ch] ? TOPIC_GLYPH[map[ch]] : '' }));
      grid.append(cell);
    }
  }
  document.getElementById('pv-rescue').replaceChildren(grid);

  // Syntax Rows: a two-line code row of caps
  const mk = (n, items, indentSock) => {
    const place = (node, col, span = 1) => {
      node.style.gridRow = '1';
      node.style.gridColumn = `${col + 2} / span ${span}`;
      return node;
    };
    const num = el('span', { class: 'mp-n', text: n });
    num.style.gridRow = '1';
    num.style.gridColumn = '1';
    const row = el('div', { class: 'mp-row' }, num);
    let col = 0;
    if (indentSock) {
      row.append(place(el('i', { class: 'sock' }), 0));
      col = 1;
    }
    for (const [text, w, topic] of items) {
      row.append(place(keycap({ topic, legend: text, legendClass: 'legend legend-c' }), col, w));
      col += w;
    }
    for (; col < 10; col++) row.append(place(el('i', { class: 'sock' }), col));
    return row;
  };
  document.getElementById('pv-rows').replaceChildren(el('div', { class: 'mp-code' },
    mk('1', [['for', 1, 'neutral'], ['i', 1, 'loops'], ['in', 1, 'neutral'], ['range(3)', 3, 'loops'], [':', 1, 'neutral']]),
    mk('2', [['print(i)', 3, 'loops']], true)));
}
