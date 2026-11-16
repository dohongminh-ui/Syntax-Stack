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
