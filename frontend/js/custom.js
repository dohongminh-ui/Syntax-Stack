// "Tạo câu đố từ code": paste a short Python program, get verified puzzles, share them by link.
// Playing reuses the Code Rescue puzzle panel as a standalone, no-penalty practice (3 tries, explanation on the last miss).
import * as api from './api.js';
import { openPuzzle } from './puzzle-modal.js';
import { TOPICS, TOPIC_NAMES, TYPE_NAMES } from './pieces.js';
import { el, toast, wait, reducedMotion } from './ui.js';
import { icon } from './icons.js';
import { keycap } from './keycap.js';
import { titleBar, codeBlock, terminal } from './editor.js';
import { showStrip, setMode, setStreak } from './strip.js';

const $ = (id) => document.getElementById(id);
const MAX_LINES = 15;
const EXPLAIN = 'Dán một chương trình Python ngắn (tối đa 15 dòng). Hệ thống chạy thử trong môi trường cách ly và tạo câu đố đã kiểm chứng.';

const EXAMPLES = [
  { label: 'Tổng bằng vòng lặp', topic: 'loops', code: 'total = 0\nfor i in range(1, 6):\n    total = total + i\nprint(total)' },
  { label: 'Xếp loại if/else', topic: 'conditions', code: 'score = 75\nif score >= 80:\n    print("Giỏi")\nelif score >= 50:\n    print("Khá")\nelse:\n    print("Cần cố gắng")' },
  { label: 'Hàm bình phương', topic: 'functions', code: 'def square(n):\n    return n * n\n\nprint(square(4))\nprint(square(5))' },
];

let nav = { show: () => {}, home: () => {}, level: () => 'beginner' };
let ed = null; // editor nodes, built once so pasted code survives leaving and re-entering the screen
let st = { view: null, set: null, preset: null, done: new Set(), playing: false, busy: false, token: 0 };

export function initCustom(n) {
  nav = { ...nav, ...n };
}

const lineCount = (text) => {
  const t = text.replace(/\s+$/, '');
  return t ? t.split('\n').length : 0;
};

function enterKey(label, onclick, { id } = {}) {
  const k = keycap({ tag: 'button', topic: 'neutral', legend: label, legendClass: 'kb-label', variant: 'btn', enter: true });
  k.type = 'button';
  if (id) k.id = id;
  k.addEventListener('click', onclick);
  return k;
}

function buildEditor() {
  const ta = el('textarea', {
    id: 'cu-code', class: 'rg-input cu-input', rows: 9, spellcheck: 'false', autocomplete: 'off', autocapitalize: 'off', autocorrect: 'off',
    'aria-label': 'Mã Python của bạn', 'aria-describedby': 'cu-count cu-keyhint',
    placeholder: '# Dán mã Python ở đây\nprint("Xin chào")',
  });
  const count = el('span', { id: 'cu-count', class: 'cu-count', text: '0/' + MAX_LINES });
  const err = el('p', { class: 'msg-err cu-err', role: 'alert', hidden: true });
  const go = enterKey('Tạo câu đố', generate, { id: 'cu-go' });
  let escaped = false;

  const sync = () => {
    const n = lineCount(ta.value);
    count.textContent = `${n}/${MAX_LINES}`;
    count.classList.toggle('over', n > MAX_LINES);
    go.disabled = st.busy || n > MAX_LINES;
    if (n > MAX_LINES) setErr(`Chương trình dài ${n} dòng. Tối đa ${MAX_LINES} dòng.`);
    else if (err.dataset.kind === 'len') setErr('');
  };
  const setErr = (msg, kind = 'len') => {
    err.hidden = !msg;
    err.dataset.kind = kind;
    err.replaceChildren(...(msg ? [icon('x', { size: 14 }), msg] : []));
  };
  ta.addEventListener('input', sync);
  ta.addEventListener('blur', () => (escaped = false));
  ta.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') { escaped = true; return; }
    if (e.key !== 'Tab') escaped = false;
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); if (!go.disabled) generate(); return; }
    // Tab indents (4 spaces). Esc then Tab leaves the field, so keyboard users are never trapped.
    if (e.key === 'Tab' && !e.shiftKey && !e.ctrlKey && !e.metaKey && !e.altKey && !escaped) {
      e.preventDefault();
      ta.setRangeText('    ', ta.selectionStart, ta.selectionEnd, 'end');
      sync();
    }
  });

  const chips = el('div', { class: 'cu-chips', role: 'group', 'aria-label': 'Ví dụ có sẵn' });
  for (const ex of EXAMPLES) {
    const c = keycap({ tag: 'button', topic: ex.topic, legend: ex.label, legendClass: 'kb-label', variant: 'btn', cls: 'cu-chip' });
    c.type = 'button';
    c.addEventListener('click', () => {
      ta.value = ex.code;
      setErr('');
      sync();
      ta.focus();
    });
    chips.append(c);
  }

  const bar = titleBar({ file: 'main.py', meta: 'Python' });
  bar.querySelector('.ed-tab').style.setProperty('--accent', 'var(--mustard)');
  const root = el('div', { class: 'cu-editor' },
    el('div', { class: 'editor' }, bar, ta,
      el('div', { class: 'cu-ed-foot' },
        el('span', { id: 'cu-keyhint', class: 'cu-keyhint', text: 'Tab thụt 4 dấu cách. Esc rồi Tab để rời ô. Ctrl+Enter để tạo.' }), count)),
    err,
    el('div', { class: 'cu-actions' },
      el('div', { class: 'cu-chips-wrap' }, el('span', { class: 'pv-label', text: 'Thử ví dụ' }), chips),
      go));
  return { root, ta, go, setErr, sync };
}

function topicOf(set) {
  return TOPICS.includes(set?.topic) ? set.topic : 'loops';
}

async function generate() {
  if (st.busy) return;
  const code = ed.ta.value.replace(/\s+$/, '');
  if (!code.trim()) {
    ed.setErr('Hãy dán một chương trình Python trước.', 'api');
    ed.ta.focus();
    return;
  }
  if (lineCount(code) > MAX_LINES) return;
  const mine = ++st.token;
  st.busy = true;
  ed.go.disabled = true;
  ed.go.querySelector('.kb-label').textContent = 'Đang chạy thử…';
  ed.setErr('');
  $('cu-result').replaceChildren(el('p', { class: 'cu-loading', role: 'status' }, icon('terminal', { size: 16 }), 'Đang chạy thử trong môi trường cách ly và kiểm chứng câu đố…'));
  try {
    const set = await api.createCustomSet({ code, level: nav.level() });
    if (mine !== st.token) return;
    st.set = set;
    st.done = new Set();
    renderResult(set);
    $('cu-result').scrollIntoView({ block: 'start', behavior: reducedMotion() ? 'auto' : 'smooth' });
  } catch (e) {
    if (mine !== st.token) return;
    $('cu-result').replaceChildren();
    if (e.status === 429) toast('Bạn tạo câu đố hơi nhanh. Hãy đợi một lát rồi thử lại.', 4200);
    else ed.setErr(e.message, 'api');
  } finally {
    if (mine === st.token) {
      st.busy = false;
      ed.go.querySelector('.kb-label').textContent = 'Tạo câu đố';
      ed.sync();
    }
  }
}

// ---- result ------------------------------------------------------------------------------------------
async function copyText(text, input) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    input.focus();
    input.select();
    try {
      return document.execCommand('copy');
    } catch {
      return false;
    }
  }
}

function shareRow(set) {
  const url = `${location.origin}/?set=${encodeURIComponent(set.id)}`;
  const input = el('input', { class: 'cu-link', type: 'text', readonly: true, value: url, id: 'cu-link', 'aria-label': 'Liên kết chia sẻ' });
  input.addEventListener('focus', () => input.select());
  const copy = el('button', { class: 'btn cu-copy', type: 'button', text: 'Sao chép liên kết' });
  copy.addEventListener('click', async () => {
    toast((await copyText(url, input)) ? 'Đã sao chép liên kết.' : 'Hãy nhấn Ctrl+C để sao chép liên kết đang được chọn.');
  });
  return el('div', { class: 'cu-share' },
    el('label', { class: 'pv-label', for: 'cu-link', text: 'Liên kết chia sẻ' }),
    el('div', { class: 'cu-share-row' }, input, copy));
}

function cardNode(p, set) {
  const done = st.done.has(p.id);
  const play = keycap({ tag: 'button', topic: topicOf(set), legend: done ? 'Chơi lại' : 'Chơi', legendClass: 'kb-label', variant: 'btn', cls: 'cu-play' });
  play.type = 'button';
  play.setAttribute('aria-label', `${done ? 'Chơi lại' : 'Chơi'}: ${TYPE_NAMES[p.type] || p.type}`);
  play.addEventListener('click', () => playOne(p));
  return el('li', { class: 'cu-card t-' + topicOf(set) + (done ? ' is-done' : ''), dataset: { id: p.id } },
    el('div', { class: 'cu-card-body' },
      el('div', { class: 'cu-card-top' },
        el('span', { class: 'chip', text: TYPE_NAMES[p.type] || p.type }),
        done ? el('span', { class: 'cu-done' }, icon('check', { size: 14 }), 'Đã giải') : null),
      el('p', { class: 'cu-prompt', text: p.prompt })),
    play);
}

function refreshCard(id) {
  const old = document.querySelector(`#cu-result .cu-card[data-id="${CSS.escape(id)}"]`);
  const p = st.set?.puzzles.find((x) => x.id === id);
  if (old && p) old.replaceWith(cardNode(p, st.set));
}

function renderResult(set, { shared = false } = {}) {
  const topic = topicOf(set);
  const out = [];
  out.push(el('div', { class: 'cu-res-head t-' + topic },
    el('span', { class: 'chip', text: TOPIC_NAMES[topic] }),
    el('h2', { class: 'cu-res-h', text: shared ? 'Sẵn sàng để giải' : 'Câu đố đã sẵn sàng' })));
  // Students opening a shared link never see the original program or its output: both give away the answers.
  if (!shared && set.expected_output != null) out.push(terminal(set.expected_output, { label: 'đầu ra của chương trình' }));
  out.push(shareRow(set));

  if (set.puzzles?.length) {
    out.push(el('div', { class: 'cu-list-head' },
      el('h2', { class: 'report-h', text: `${set.puzzles.length} câu đố` }),
      enterKey('Chơi lần lượt', playAll, { id: 'cu-all' })));
    if (st.preset?.onReview) {
      const review = enterKey('Ôn lại với Misaki', st.preset.onReview, { id: 'cu-misaki-review' });
      review.hidden = true;
      out.push(review);
    }
    out.push(el('ol', { class: 'cu-list' }, set.puzzles.map((p) => cardNode(p, set))));
  } else {
    out.push(el('p', { class: 'cm', text: 'Chưa tạo được câu đố nào từ chương trình này. Hãy thử một chương trình khác.' }));
  }
  if (set.skipped?.length) {
    out.push(el('p', { class: 'cu-skipped' }, 'Không tạo được: ',
      set.skipped.map((s, i) => `${i ? '; ' : ''}${TYPE_NAMES[s.type] || s.type}${s.reason ? ` (${s.reason})` : ''}`).join('')));
  }
  $('cu-result').replaceChildren(...out);
}

// ---- playing -----------------------------------------------------------------------------------------
function playOne(p) {
  return openOne(p, 'Về bộ câu đố').then((res) => {
    document.querySelector(`#cu-result .cu-card[data-id="${CSS.escape(p.id)}"] .cu-play`)?.focus({ preventScroll: true });
    return res;
  });
}

async function openOne(p, closeLabel) {
  if (st.playing) return { response: null };
  const { set, preset } = st;
  st.playing = true;
  try {
    const res = await openPuzzle({
      puzzle: p, topic: topicOf(set), title: 'Câu đố của bạn', tag: 'TỰ TẠO',
      maxAttempts: 3, penalties: false, standalone: true, closeLabel, track: false,
      onAttempt: preset?.onAttempt ? (answer) => {
        if (st.set !== set) return;
        preset.onAttempt(p.id, answer);
        const review = $('cu-misaki-review');
        if (review) review.hidden = false;
      } : null,
    });
    if (res.correct && st.set === set) {
      st.done.add(p.id);
      refreshCard(p.id);
    }
    return res;
  } finally {
    st.playing = false;
  }
}

async function playAll() {
  const set = st.set;
  if (!set?.puzzles?.length) return;
  let queue = set.puzzles.filter((p) => !st.done.has(p.id));
  if (!queue.length) queue = set.puzzles.slice();
  for (let i = 0; i < queue.length; i++) {
    if ($('screen-custom').hidden || st.set !== set) return;
    const res = await openOne(queue[i], `Dừng (${i + 1}/${queue.length})`);
    if (!res.response) break; // closed before answering: stop the run
    await wait(220); // let the closing panel finish before the next one mounts
  }
  $('cu-all')?.focus({ preventScroll: true });
}

// ---- screen entry ------------------------------------------------------------------------------------
function frame(shared, preset = null) {
  nav.show('screen-custom');
  showStrip(true, { back: preset?.back || nav.home, backLabel: preset?.backLabel || 'Về màn hình chính' });
  setMode(preset ? 'CÂU ĐỐ TỪ MISAKI' : shared ? 'BỘ CÂU ĐỐ CHIA SẺ' : 'TẠO CÂU ĐỐ');
  setStreak(null);
  $('cu-title').textContent = preset ? 'Câu đố từ Misaki' : shared ? 'Bộ câu đố được chia sẻ' : 'Tạo câu đố từ code';
  $('cu-sub').textContent = preset ? preset.note || 'Misaki viết một chương trình Python nhỏ, hệ thống kiểm chứng và biến nó thành câu đố.'
    : shared ? 'Một bộ câu đố được tạo từ chương trình Python của người khác. Giải thử và xem bạn đúng được mấy câu.' : EXPLAIN;
  $('cu-title').focus({ preventScroll: true });
}

/**
 * Opens the custom-puzzle screen. `shared`: the id of a set to load. `preset`: a set already in hand
 * ({ set, note, back, backLabel, onAttempt, onReview }), as made by "Chat with Misaki"; it plays like a shared set.
 */
export function openCustom({ shared = null, preset = null } = {}) {
  st.token++;
  st.busy = false;
  st.preset = preset;
  const editorSlot = $('cu-editor');
  const result = $('cu-result');
  if (preset) {
    st.view = 'preset';
    frame(true, preset);
    editorSlot.replaceChildren();
    st.set = preset.set;
    st.done = new Set();
    renderResult(preset.set, { shared: true });
    return Promise.resolve();
  }
  if (shared) {
    st.view = 'shared';
    frame(true);
    editorSlot.replaceChildren();
    return loadShared(shared);
  }
  ed = ed || buildEditor();
  if (st.view !== 'make') {
    st.set = null;
    st.done = new Set();
    result.replaceChildren();
  }
  st.view = 'make';
  frame(false);
  editorSlot.replaceChildren(ed.root);
  ed.sync();
  return Promise.resolve();
}

async function loadShared(id) {
  const mine = st.token;
  const result = $('cu-result');
  st.set = null;
  st.done = new Set();
  result.replaceChildren(el('p', { class: 'cu-loading', role: 'status' }, icon('terminal', { size: 16 }), 'Đang tải bộ câu đố…'));
  try {
    const set = await api.getCustomSet(id, nav.level());
    if (mine !== st.token) return;
    st.set = set;
    renderResult(set, { shared: true });
  } catch (e) {
    if (mine !== st.token) return;
    const mk = enterKey('Tạo câu đố của riêng bạn', () => openCustom());
    if (e.status === 404) {
      result.replaceChildren(el('div', { class: 'cu-missing' },
        el('h2', { class: 'cu-res-h', text: 'Không tìm thấy bộ câu đố này' }),
        el('p', { class: 'cu-missing-p', text: 'Liên kết có thể đã hết hạn hoặc bị gõ sai. Bạn có thể tự tạo một bộ câu đố từ mã Python của mình.' }), mk));
    } else {
      result.replaceChildren(el('div', { class: 'cu-missing' },
        el('p', { class: 'msg-err', role: 'alert' }, icon('x', { size: 14 }), 'Không tải được bộ câu đố: ' + e.message),
        el('button', { class: 'btn', type: 'button', text: 'Thử lại', onclick: () => loadShared(id) }), mk));
    }
  }
}
