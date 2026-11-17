// Syntax Rows screens: level select + game. Glue between rows-game.js (rules), rows-board.js (board), the API and the strip.
import * as api from './api.js';
import * as store from './storage.js';
import * as R from './rows-game.js';
import { RowsBoard } from './rows-board.js';
import { el, anim, EASE, wait, toast, reducedMotion } from './ui.js';
import { icon } from './icons.js';
import { keycap } from './keycap.js';
import { titleBar, codeBlock, terminal, comment, tutorNote } from './editor.js';
import { showStrip, setMode, setScore, setStatus, setStreak, setLedMode } from './strip.js';
import { setLevelTitle } from './title.js';
import { sfx } from './sound.js';

const $ = (id) => document.getElementById(id);
let nav = { show: () => {}, home: () => {} };
let levels = null;
let progress = {};
let board = null;
let G = null; // current game { state, concept, busy, view, resp }

export function initRows(n) {
  nav = n;
  document.addEventListener('keydown', onTraceKey);
}

/** Left/right step through an open trace. Never steals arrows from inputs, the board or the tray. */
function onTraceKey(e) {
  if (!G?.parts?.trace || G.parts.trace.hidden || !G.parts.trace.open) return;
  if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
  if (e.altKey || e.ctrlKey || e.metaKey || e.shiftKey || document.querySelector('.dialog-backdrop')) return;
  const t = e.target;
  if (t.closest?.('textarea, input, select, [contenteditable], .rows-board, .rows-tray')) return;
  if (t !== document.body && !t.closest?.('#rg-side')) return;
  e.preventDefault();
  moveTrace(e.key === 'ArrowLeft' ? -1 : 1);
}

function disclosure(label, ...children) {
  return el('details', { class: 'rg-trace' },
    el('summary', {}, icon('chevron-right', { size: 16, cls: 'chev' }), el('span', { text: label })), ...children);
}

function stepKey(name, label, onclick) {
  const k = keycap({ tag: 'button', topic: 'neutral', legend: icon(name, { size: 18 }), legendClass: 'legend legend-c', cls: 'sk' });
  k.type = 'button';
  k.setAttribute('aria-label', label);
  k.addEventListener('click', onclick);
  return k;
}

/** Textarea that grows with its content (CSS sets min 3 / max 8 lines). */
function autoGrow(ta) {
  ta.style.height = 'auto';
  ta.style.height = ta.scrollHeight + 2 + 'px';
}

function terminalInput(attrs) {
  const ta = el('textarea', { class: 'rg-input', rows: 3, spellcheck: 'false', autocomplete: 'off', ...attrs });
  ta.addEventListener('input', () => autoGrow(ta));
  return ta;
}

/** kind: 'bonus' | 'ok' (correct) | 'bad' (wrong) | 'none' (could not compare) | null (clear). */
function setPrediction(node, kind) {
  if (kind === 'bonus') sfx('chime');
  node.className = 'rg-prediction' + (kind === 'ok' || kind === 'bonus' ? ' ok' : kind === 'bad' ? ' bad' : '');
  if (kind == null) node.replaceChildren();
  else if (kind === 'bonus') node.replaceChildren(icon('check', { size: 16 }), el('span', {}, 'Dự đoán đúng. ', el('b', { class: 'rg-bonus', text: `+${R.PREDICT_BONUS} Đọc code` })));
  else if (kind === 'ok') node.replaceChildren(icon('check', { size: 16 }), el('span', { text: 'Dự đoán đúng' }));
  else if (kind === 'bad') node.replaceChildren(icon('x', { size: 16 }), el('span', { text: 'Dự đoán chưa đúng, so sánh với đầu ra thực tế' }));
  else node.replaceChildren(el('span', { text: 'Chương trình chưa chạy xong để đối chiếu dự đoán.' }));
}

// ---- helpers ------------------------------------------------------------------------------------------
function enterKey(label, onclick, { disabled = false, id } = {}) {
  const k = keycap({ tag: 'button', topic: 'neutral', legend: label, legendClass: 'kb-label', variant: 'btn', enter: true });
  k.type = 'button';
  if (id) k.id = id;
  k.disabled = disabled;
  k.addEventListener('click', onclick);
  return k;
}

function starIcons(n, size, cls = '') {
  const wrap = [];
  for (let i = 0; i < 3; i++) wrap.push(icon('star', { size, fill: i < n, cls: (i < n ? 'on ' : '') + cls }));
  return wrap;
}

async function loadLevels() {
  levels = await api.rowsLevels();
  levels.sort((a, b) => a.order - b.order);
  progress = store.loadRowsProgress();
  return levels;
}

// ---- level select -----------------------------------------------------------------------------------------
export async function openSelect() {
  G = null;
  nav.show('screen-rows-select');
  showStrip(true, { back: nav.home, backLabel: 'Về màn hình chính' });
  setMode('SYNTAX ROWS');
  setLedMode('rows');
  setStreak(null);
  const err = $('rs-error');
  err.hidden = true;
  const list = $('rs-levels');
  try {
    await loadLevels();
  } catch (e) {
    list.textContent = '';
    err.hidden = false;
    err.textContent = '';
    err.append(icon('x', { size: 16 }), 'Không tải được danh sách màn: ' + e.message, el('button', { class: 'btn', type: 'button', text: 'Thử lại', onclick: openSelect }));
    return;
  }
  const t = R.totals(levels, progress);
  setScore(t.score, { roll: false });
  $('rs-progress').replaceChildren(
    el('span', { class: 'stat' }, icon('check', { size: 14 }), el('b', { text: `${t.done}/${levels.length}` }), ' màn'),
    el('span', { class: 'stat' }, icon('star', { size: 14, fill: true }), el('b', { text: `${t.stars}/${t.max}` }), ' sao'),
    el('span', { class: 'stat', text: `${t.score} điểm` }),
  );
  for (const li of document.querySelectorAll('#rs-stars li:not(.ready)')) {
    li.classList.add('ready');
    li.prepend(el('span', { class: 'st', 'aria-label': li.dataset.n + ' sao' }, starIcons(+li.dataset.n, 14)));
  }
  list.textContent = '';
  for (const lv of levels) {
    const p = progress[lv.id];
    const open = R.isUnlocked(levels, progress, lv.id);
    const k = keycap({ tag: 'button', topic: lv.concept, legend: '', legendClass: 'lvl-body', cls: 'lvl-key' });
    k.type = 'button';
    k.disabled = !open;
    const body = k.querySelector('.lvl-body');
    body.append(el('span', { class: 'lvl-n', text: String(lv.order).padStart(2, '0') }), el('span', { class: 'lvl-t', text: lv.title }));
    if (!open) k.firstElementChild.append(icon('lock', { size: 18, cls: 'lvl-lock' }));
    k.setAttribute('aria-label', open ? `Màn ${lv.order}: ${lv.title}. ${p?.stars || 0} trên 3 sao.` : `Màn ${lv.order}: ${lv.title}. Đang khóa, hoàn thành màn trước để mở.`);
    k.addEventListener('click', () => openLevel(lv.id));
    const li = el('li', { class: 'lvl' + (open ? '' : ' is-locked') }, k, el('div', { class: 'lvl-stars', 'aria-hidden': 'true' }, starIcons(p?.stars || 0, 18)));
    list.append(li);
  }
}

// ---- game -----------------------------------------------------------------------------------------------------
function ensureBoard() {
  if (board) return;
  board = new RowsBoard({
    boardEl: $('rows-board'),
    trayEl: $('rows-tray'),
    trayWrapEl: document.querySelector('.rows-tray-wrap'),
    countEl: $('rows-tray-count'),
    handlers: {
      getState: () => G.state,
      getErrorRow: () => G.state.errorRow,
      onPlace: (id, row, col) => edit(() => R.place(G.state, id, row, col)),
      onRemove: (id) => edit(() => R.remove(G.state, id)),
      onHint: (t) => toast(t, 2600),
    },
  });
}

/** Any board edit: apply, clear the red marks (the message stays until the next run), refresh. */
function edit(fn) {
  if (!G || G.busy || G.hintBusy || G.state.passed) return;
  fn();
  const traceWasOpen = G.parts.trace.open;
  setTrace(null);
  G.parts.predictInput.value = '';
  autoGrow(G.parts.predictInput);
  setPrediction(G.parts.predictionResult, null);
  if (traceWasOpen) {
    renderPane();
    renderActions();
  }
  G.state.errorRow = null;
  board.render(G.state, { errorRow: null });
  renderCode();
  G.parts.pane.classList.toggle('stale', G.view === 'fail');
}

export async function openLevel(id, { startingRows = [], baseline = null, returnTo = null } = {}) {
  ensureBoard();
  if (!levels) {
    try {
      await loadLevels();
    } catch (e) {
      toast('Không tải được màn chơi: ' + e.message);
      return openSelect();
    }
  }
  let level;
  try {
    level = await api.rowsLevel(id);
  } catch (e) {
    toast('Không tải được màn chơi: ' + e.message);
    return;
  }
  const meta = levels.find((l) => l.id === id) || { concept: 'variables', order: level.order };
  G = {
    state: R.newState(level), concept: meta.concept, busy: false, view: 'idle', resp: null,
    parts: {}, baseline, returnTo, next: levels[levels.findIndex((l) => l.id === id) + 1] || null,
  };
  for (const row of startingRows) {
    for (const token of row.tokens) R.place(G.state, token.id, row.row, token.col);
  }
  nav.show('screen-rows');
  $('screen-rows').className = 'screen rows-screen t-' + meta.concept;
  showStrip(true, { back: returnTo || openSelect, backLabel: returnTo ? 'Về bài luyện' : 'Về danh sách màn' });
  setMode(`SYNTAX ROWS · MÀN ${meta.order}`);
  setLedMode('rows');
  setStreak(null);
  setScore(R.totals(levels, progress).score, { roll: false });
  const chip = $('rg-num');
  chip.className = 'chip t-' + meta.concept;
  chip.textContent = `MÀN ${meta.order}`;
  $('rg-title').textContent = level.title;
  setLevelTitle(meta.order, level.title);
  $('rg-goal').textContent = baseline ? 'Thay đúng một mảnh mã ở cùng vị trí để có đầu ra mới.' : level.goal;
  board.setLevel(G.state);
  buildSide();
  return G;
}

export async function openPracticeRows(id, mode, returnTo, previousRows = null) {
  try {
    const startingRows = previousRows || (await api.rowsPractice(id)).rows;
    const game = await openLevel(id, { startingRows, returnTo });
    if (!game) return;
    if (mode === 'predict') game.parts.predict.open = true;
    if (mode === 'trace') {
      await run();
      if (G === game && game.trace?.steps.length) game.parts.trace.open = true;
    }
  } catch (e) {
    toast('Không tải được bài luyện: ' + e.message);
  }
}

// ---- editor side panel ------------------------------------------------------------------------------------------
function buildSide() {
  const p = (G.parts = {
    bar: el('div'),
    vwrap: el('div'),
    code: el('div'),
    predict: null,
    predictInput: terminalInput({ maxlength: 240, 'aria-label': 'Đầu ra dự đoán', placeholder: 'Mỗi giá trị trên một dòng' }),
    predictionResult: el('p', { class: 'rg-prediction', role: 'status' }),
    trace: null,
    traceStep: el('div', { class: 'rg-trace-step', 'aria-live': 'polite' }),
    tracePrev: stepKey('chevron-left', 'Bước trước', () => moveTrace(-1)),
    traceNext: stepKey('chevron-right', 'Bước tiếp', () => moveTrace(1)),
    traceTrack: el('div', { class: 'rg-track' }),
    pane: el('div', { class: 'rg-pane' }),
    actions: el('div', { class: 'rg-actions' }),
    result: el('div'),
  });
  const options = (G.state.level.predictions || []).map((guess) =>
    el('button', { type: 'button', class: 'btn', text: guess.replaceAll('\n', ' · '),
      onclick: () => { if (!p.predictInput.disabled) { p.predictInput.value = guess; autoGrow(p.predictInput); } } }));
  p.predict = disclosure('Dự đoán đầu ra',
    el('div', { class: 'rg-trace-body' },
      comment(`Đoán chương trình của bạn sẽ in gì trước khi chạy. Đoán đúng đầu ra của một chương trình chưa đạt: +${R.PREDICT_BONUS} điểm Đọc code (1 lần mỗi màn).`),
      options.length ? el('div', { class: 'rg-trace-controls' }, options) : null,
      el('div', { class: 'rg-field' }, el('div', { class: 'term-ps', text: '$ dự đoán' }), p.predictInput)));
  p.predict.hidden = !!G.baseline;
  p.predict.addEventListener('toggle', () => autoGrow(p.predictInput));
  p.trace = disclosure('Theo dõi từng bước',
    el('div', { class: 'rg-trace-body' }, p.traceStep,
      el('div', { class: 'rg-stepper' }, p.tracePrev, p.traceTrack, p.traceNext)));
  p.trace.hidden = true;
  p.trace.addEventListener('toggle', () => {
    if (G?.parts !== p || p.trace.hidden) return;
    renderTrace();
    renderCode();
    renderPane();
    renderActions();
  });
  const editor = el('div', { class: 'editor rg-editor' }, p.bar, p.vwrap, p.code, p.predict, p.predictionResult, p.trace, p.pane);
  $('rg-side').replaceChildren(editor, p.actions, p.result);
  renderBar();
  renderCode();
  renderPane();
  renderActions();
}

function renderBar() {
  const s = G.state;
  G.parts.bar.replaceChildren(titleBar({ file: 'main.py', meta: s.passed ? 'đã chạy đúng' : `lần chạy ${s.runs}`, check: s.passed }));
}

function renderCode(passed = G.state.passed) {
  const active = G.parts.trace.open ? G.trace?.steps[G.traceIndex]?.row : null;
  board.setTraceRow(active);
  const lines = R.previewLines(G.state).map((l) => ({
    ...l,
    cls: l.row === active ? 'trace-active' : l.row === G.state.errorRow ? 'err' : passed && l.text ? 'ok' : '',
  }));
  G.parts.code.replaceChildren(codeBlock(lines, { label: 'Mã đang ghép' }));
}

function setTrace(trace) {
  const panel = G.parts.trace;
  G.trace = trace;
  G.traceIndex = 0;
  panel.open = false;
  panel.hidden = !trace?.steps.length;
  if (!panel.hidden) renderTrace();
}

function moveTrace(delta) {
  const index = G.traceIndex + delta;
  if (!G.trace?.steps[index]) return;
  G.traceIndex = index;
  renderTrace();
  renderCode();
}

function renderTrace() {
  const { parts, trace, traceIndex: index } = G;
  const step = trace?.steps[index];
  if (!step) return;
  const bindings = Object.entries(step.bindings).map(([name, value]) =>
    el('code', {}, el('span', { class: 'bn', text: name }), el('span', { class: 'bq', text: ' = ' }), el('span', { class: 'bv', text: String(value) })));
  const last = index === trace.steps.length - 1;
  parts.tracePrev.disabled = index === 0;
  parts.traceNext.disabled = last;
  const total = trace.steps.length;
  parts.traceTrack.setAttribute('role', 'img');
  parts.traceTrack.setAttribute('aria-label', `Bước ${index + 1} trên ${total}`);
  parts.traceTrack.replaceChildren(
    el('span', { class: 'rg-dots', 'aria-hidden': 'true' }, trace.steps.map((_, i) => el('i', { class: i === index ? 'cur' : i < index ? 'past' : '' }))),
    el('span', { class: 'rg-count', 'aria-hidden': 'true', text: `${index + 1}/${total}` }));
  const snapshot = [
    el('p', { class: 'rg-trace-position', text: `Hàng ${step.row + 1}${step.scope ? ` · ${step.scope}()` : ''}` }),
    bindings.length ? el('div', { class: 'rg-trace-bindings', 'aria-label': 'Giá trị biến' }, ...bindings) : null,
    terminal(step.output || '(chưa có đầu ra)', { label: 'đầu ra đến bước này' }),
    last && trace.truncated ? comment('Bản ghi dừng ở bước này. Chương trình đã tiếp tục chạy.') : null,
  ];
  parts.traceStep.replaceChildren(...snapshot.filter(Boolean));
}

function renderPane() {
  const { state: s, parts } = G;
  const nodes = [];
  const expected = G.baseline ? s.level.twist_output : s.level.expected_output;
  if (!parts.trace.open) {
    if (G.view === 'fail' && G.resp?.expected_output != null) {
      nodes.push(el('div', { class: 'term-cmp' },
        terminal(G.resp.actual_output || '(không có đầu ra)', { label: 'đầu ra thực tế', cls: 'is-bad' }),
        terminal(expected, { label: 'đầu ra mong đợi', cls: 'is-ok' })));
    } else if (G.view === 'pass') {
      nodes.push(G.passTerm);
    } else {
      nodes.push(terminal(expected, { label: 'đầu ra mong đợi' }));
    }
  }
  if (s.hintsShown.length && G.view !== 'pass') {
    const hl = el('div', { class: 'hints', 'aria-live': 'polite' });
    s.hintsShown.forEach((h, i) => {
      const ai = h.source === 'ai';
      const context = ai ? `gợi ý ${i + 1}${h.step ? ` · bước ${h.step}` : ''}` : `Gợi ý ${i + 1}${h.step ? ` (bước ${h.step})` : ''}`;
      hl.append(tutorNote({ text: h.text, source: ai ? 'ai' : 'canned', context }));
    });
    nodes.push(hl);
  }
  if (G.note) nodes.push(el('p', { class: 'msg-err', role: 'alert' }, icon('x', { size: 14 }), G.note));
  parts.pane.replaceChildren(...nodes);
  parts.pane.classList.remove('stale');
}

function renderActions() {
  const { state: s, parts } = G;
  parts.predictInput.disabled = G.busy || s.passed;
  if (s.passed) {
    parts.actions.hidden = true;
    return;
  }
  parts.actions.hidden = false;
  const n = s.hintsShown.length + 1;
  const hintLabel = parts.trace.open ? `Gợi ý bước này · ${n}/3` : `Gợi ý ${n}/3`;
  const hint = G.baseline ? null : n <= 3
    ? el('button', { class: 'btn', type: 'button', disabled: G.busy || G.hintBusy, onclick: showHint },
        icon('bulb', { size: 18 }), G.hintBusy ? 'Đang tải gợi ý…' : hintLabel,
        el('span', { class: 'pen', text: ` · tối đa ${n === 1 ? 2 : 1} sao` }))
    : el('span', { class: 'hint-done', text: 'Đã xem hết gợi ý' });
  parts.actions.replaceChildren(...[hint, enterKey(G.busy ? 'Đang chạy…' : 'Chạy kiểm tra', run,
    { disabled: G.busy || G.hintBusy, id: 'rows-run' })].filter(Boolean));
}

async function showHint() {
  const game = G;
  const s = game.state;
  const n = s.hintsShown.length + 1;
  if (n > 3 || game.busy || game.hintBusy) return;
  game.hintBusy = true;
  game.note = '';
  renderActions();
  const step = game.parts.trace.open ? game.traceIndex + 1 : null;
  const attempt = step ? { ...game.lastAttempt, trace_step: step - 1 } : game.lastAttempt;
  try {
    const h = await api.rowsHint(s.level.id, n, s.lastGroup, attempt);
    R.addHint(s, { ...h, step });
  } catch (e) {
    game.note = 'Không tải được gợi ý: ' + e.message;
  }
  game.hintBusy = false;
  if (game !== G) return;
  renderPane();
  renderActions();
}

// ---- run ------------------------------------------------------------------------------------------------------------------
function showValidator(resp) {
  const row = resp.row != null ? `Hàng ${resp.row + 1} · ` : '';
  const line = el('div', { class: 'vline', role: 'alert' },
    el('span', { class: 'chip', text: R.GROUP_LABEL[resp.error_group] || 'Lỗi' }),
    el('span', { text: row + resp.message }));
  G.parts.vwrap.replaceChildren(line);
  anim(line, [
    { transform: 'translateY(-10px)', opacity: 0, clipPath: 'inset(0 0 100% 0)' },
    { transform: 'translateY(0)', opacity: 1, clipPath: 'inset(0 0 0 0)' },
  ], { duration: 200, easing: EASE.out });
}

function onFail(resp, { local = false } = {}) {
  const s = G.state;
  G.view = 'fail';
  G.resp = local ? null : resp;
  setTrace(resp.trace);
  if (!G.returnTo && !G.baseline && !api.isMock && resp.error_group !== 'empty') {
    store.recordMistake({ topic: G.concept, levelId: s.level.id, errorGroup: resp.error_group,
      rows: local ? null : G.lastAttempt?.rows });
  }
  s.errorRow = resp.row ?? null;
  s.lastGroup = resp.error_group;
  R.setHintContext(s, resp.error_group);
  board.render(s, { errorRow: s.errorRow });
  board.flagError(s.errorRow);
  if (!local) sfx('bzzt');
  renderBar();
  renderCode();
  showValidator(resp);
  renderPane();
  setStatus('fail');
  $('rg-side').scrollIntoView({ block: 'nearest', behavior: reducedMotion() ? 'auto' : 'smooth' });
}

async function typeInto(node, text) {
  node.textContent = '';
  if (reducedMotion()) {
    node.textContent = text;
    return;
  }
  const chars = [...text];
  const per = Math.min(20, 600 / Math.max(1, chars.length));
  for (const ch of chars) {
    node.textContent += ch;
    sfx('type');
    await wait(per);
  }
}

async function onPass(resp) {
  const game = G;
  const s = game.state;
  const stars = R.starsFor(s.runs, s.hintsMax);
  const score = R.scoreFor(stars, resp.unused_distractors || 0, s.readBonus);
  if (!game.baseline && !game.returnTo) progress = store.recordRowsResult(s.level.id, stars, score);
  s.passed = true;
  s.errorRow = null;
  s.result = { stars, score, unused: resp.unused_distractors || 0, runs: s.runs, hints: s.hintsMax, read: s.readBonus };
  G.view = 'pass';
  setTrace(resp.trace);
  G.parts.vwrap.replaceChildren();
  renderBar();
  renderCode(true);
  renderActions();
  setStatus('pass');
  if (s.runs > 1) sfx('resolve');
  const term = terminal('', { label: 'đầu ra', cls: 'is-ok' });
  G.passTerm = term;
  renderPane();
  const out = term.querySelector('.term-out');
  const text = resp.actual_output ?? s.level.expected_output;
  await Promise.all([board.animateCompile(R.lines(s)), wait(260).then(() => typeInto(out, text))]);
  if (G !== game) return;
  showResult();
  setScore(R.totals(levels, progress).score, { roll: true });
}

function teachBackPanel(game) {
  const input = terminalInput({ maxlength: 400, required: true,
    'aria-label': 'Lời giải thích của bạn', placeholder: 'Giải thích bằng tiếng Việt hoặc tiếng Anh' });
  const reply = el('div', { class: 'rg-teach-reply', role: 'status' });
  const submit = keycap({ tag: 'button', topic: 'neutral', legend: 'Hỏi gia sư', legendClass: 'kb-label', variant: 'btn', enter: true, cls: 'key-sm' });
  submit.type = 'submit';
  const form = el('form', { class: 'rg-trace-body', onsubmit: async (event) => {
    event.preventDefault();
    const reflection = input.value.trim();
    if (!reflection || submit.disabled) return;
    submit.disabled = true;
    input.disabled = true;
    reply.replaceChildren(tutorNote({ loading: true }));
    try {
      const feedback = await api.teachBack(game.state.level.id, { ...game.lastAttempt, reflection });
      reply.replaceChildren(tutorNote({ text: feedback.text, source: feedback.source === 'ai' ? 'ai' : 'canned', context: 'phản hồi' }));
    } catch (e) {
      reply.replaceChildren(el('p', { class: 'msg-err' }, icon('x', { size: 14 }), 'Không tải được phản hồi: ' + e.message));
    } finally {
      submit.disabled = false;
      input.disabled = false;
    }
  } }, el('div', { class: 'rg-field' }, input),
    // Responsible-AI rule from the proposal: the learner's own words leave the device, so say so.
    el('p', { class: 'rg-privacy', id: 'rg-privacy-note', text: 'Lời giải thích của bạn được gửi tới gia sư AI. Đừng ghi tên, số điện thoại hay thông tin cá nhân.' }),
    el('div', { class: 'rg-submit' }, submit), reply);
  input.setAttribute('aria-describedby', 'rg-privacy-note');
  const d = disclosure('Giải thích lại', form);
  d.addEventListener('toggle', () => autoGrow(input));
  return d;
}

function twistButton(game) {
  const { state: { level }, lastAttempt, returnTo } = game;
  if (level.twist_output == null) return null;
  const k = keycap({ tag: 'button', topic: 'neutral', legend: el('span', { class: 'kb-inline' }, icon('shuffle', { size: 18 }), 'Đổi một mảnh'), legendClass: 'kb-label', variant: 'btn', cls: 'key-secondary' });
  k.type = 'button';
  k.addEventListener('click', () => openLevel(level.id, { startingRows: lastAttempt.rows, baseline: lastAttempt.rows, returnTo }));
  return k;
}

function showResult() {
  const game = G;
  const { state: s } = game;
  if (game.baseline || game.returnTo) {
    G.parts.result.replaceChildren(el('div', { class: 'rg-result' },
      el('h2', { text: game.baseline ? 'Đổi một mảnh thành công!' : 'Hoàn thành bài luyện!' }),
      game.baseline ? null : teachBackPanel(game),
      el('div', { class: 'res-actions' }, el('div', { class: 'res-keys' }, game.baseline ? null : twistButton(game),
        enterKey(game.returnTo ? 'Về bài luyện' : 'Chọn màn', game.returnTo || openSelect)))));
    return;
  }
  const r = s.result;
  const stars = el('div', { class: 'rg-stars', role: 'img', 'aria-label': `${r.stars} trên 3 sao` }, starIcons(r.stars, 34));
  const next = G.next;
  const reveal = el('div', { class: 'rg-result' },
    stars,
    el('h2', { text: r.stars === 3 ? 'Hoàn hảo!' : 'Hoàn thành!' }),
    el('dl', { class: 'receipt', 'aria-label': 'Kết quả màn chơi' },
      ...[['stars', `${r.stars}/3`], ['runs', r.runs], ['hints_used', r.hints], ['unused_distractors', r.unused], ['read_code', r.read ? `+${R.PREDICT_BONUS}` : '0'], ['level_score', r.score]].map(([k, v]) => el('div', {}, el('dt', { text: k }), el('dd', { text: String(v) })))),
    r.stars < 3 ? comment('Chơi lại để lấy thêm sao: đạt ngay lần chạy đầu, không dùng gợi ý.') : null,
    teachBackPanel(game),
    el('div', { class: 'res-actions' },
      el('div', { class: 'res-keys' }, twistButton(game),
        next ? enterKey('Màn tiếp theo', () => openLevel(next.id), { id: 'rows-next' }) : enterKey('Chọn màn', openSelect, { id: 'rows-next' })),
      el('div', { class: 'res-links' },
        el('button', { class: 'btn', type: 'button', text: 'Chơi lại màn', onclick: () => openLevel(s.level.id) }),
        next ? el('button', { class: 'btn', type: 'button', text: 'Chọn màn', onclick: openSelect }) : null)));
  G.parts.result.replaceChildren(reveal);
  anim(reveal, [{ transform: 'translateY(8px)', opacity: 0 }, { transform: 'none', opacity: 1 }], { duration: 240, easing: EASE.out });
  const icons = [...stars.querySelectorAll('.ico.on')];
  icons.forEach((ic, i) => {
    starSfx(i, r.stars);
    anim(ic, [{ transform: 'scale(.9)', opacity: 0.2 }, { transform: 'scale(1.15)', opacity: 1, offset: 0.6 }, { transform: 'scale(1)', opacity: 1 }], { duration: 320, delay: 120 + i * 140, easing: EASE.out, fill: 'backwards' });
  });
  reveal.scrollIntoView({ block: 'nearest', behavior: reducedMotion() ? 'auto' : 'smooth' });
}

function starSfx(i, total) {
  const at = 120 + i * 140;
  setTimeout(() => sfx('star', { i }), at);
  if (total === 3 && i === 2) setTimeout(() => sfx('perfect'), at + 160);
}

async function run() {
  if (!G || G.busy || G.hintBusy || G.state.passed) return;
  const game = G;
  const s = game.state;
  setPrediction(game.parts.predictionResult, null);
  const local = R.localCheck(s);
  if (local) {
    game.lastAttempt = null;
    sfx('nope');
    return onFail({ ...local, actual_output: null, expected_output: null }, { local: true });
  }
  sfx('enter');
  G.busy = true;
  G.note = '';
  setStatus('run', { blink: false });
  renderActions();
  const attempt = R.payload(s);
  const prediction = game.parts.predict.open ? game.parts.predictInput.value.trimEnd() : '';
  let resp;
  try {
    const request = { ...attempt, trace: true, prediction: prediction || undefined };
    resp = game.baseline
      ? await api.rowsTwist(s.level.id, { ...request, baseline: game.baseline })
      : await api.rowsRun(s.level.id, request);
  } catch (e) {
    if (game !== G) return;
    G.busy = false;
    setStatus(null);
    G.note = game.baseline ? e.message : 'Không chạy được: ' + e.message + '. Hãy thử lại.';
    renderPane();
    renderActions();
    return;
  }
  if (game !== G) return;
  game.lastAttempt = attempt;
  const verdict = R.notePrediction(s, attempt, resp);
  if (verdict) setPrediction(game.parts.predictionResult, verdict === 'bonus' && game.baseline ? 'ok' : verdict);
  R.recordRun(s);
  if (resp.passed) await onPass(resp);
  else onFail(resp);
  game.busy = false;
  if (game !== G) return;
  renderActions();
}

// ---- demo hooks ---------------------------------------------------------------------------------------------------------------
// ?demo=rows-select | rows-3 | rows-3-fail | rows-trace | rows-pass
function demoPlace(list) {
  for (const [text, row, col] of list) {
    const t = G.state.level.tokens.find((x) => x.text === text && !G.state.placed[x.id]);
    if (t) R.place(G.state, t.id, row, col);
  }
  board.render(G.state, { animate: false });
  renderCode();
}

export async function runDemo(name) {
  if (name === 'rows-select') {
    store.saveRowsProgress({ r1: { stars: 3, score: 400 }, r2: { stars: 2, score: 250 } });
    return openSelect();
  }
  if (name !== 'rows-trace') {
    store.saveRowsProgress({ r1: { stars: 3, score: 400 }, r2: { stars: 2, score: 250 } });
  }
  await openLevel('r3');
  const head = [['for', 0, 0], ['i', 0, 1], ['in', 0, 2]];
  if (name === 'rows-3') {
    demoPlace([...head, ['range(2)', 0, 3], [':', 0, 6]]);
  } else if (name === 'rows-3-fail' || name === 'rows-trace') {
    demoPlace([...head, ['range(2)', 0, 3], [':', 0, 6], ['print(i)', 1, 1]]);
    await run();
    if (name === 'rows-3-fail') await showHint();
    else if (G?.trace?.steps.length) G.parts.trace.open = true;
  } else if (name === 'rows-pass') {
    demoPlace([...head, ['range(3)', 0, 3], [':', 0, 6], ['print(i)', 1, 1]]);
    await run();
  }
}
