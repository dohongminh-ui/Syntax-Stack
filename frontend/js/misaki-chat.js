// "Chat with Misaki" (docs/misaki-chat.md): the learner talks to the game's AI character, she answers in text and with
// her Live2D model (misaki-stage.js), and may propose ONE action as an Enter keycap under her bubble. An action never
// runs without a click. The validator decides, the AI explains: puzzles she makes go through the server's custom-set
// pipeline and are played in the custom-puzzle screen. History lives in this module and in sessionStorage.
import * as api from './api.js';
import * as store from './storage.js';
import { TOPICS, TOPIC_NAMES } from './pieces.js';
import { el, toast, reducedMotion } from './ui.js';
import { keycap } from './keycap.js';
import { icon } from './icons.js';
import { titleBar, richText } from './editor.js';
import { misakiAvatar, misakiTitle } from './misaki.js';
import { showStrip, setMode, setStreak } from './strip.js';
import { openCustom } from './custom.js';
import { mountStage } from './misaki-stage.js';
import { t } from './i18n.js';

const $ = (id) => document.getElementById(id);
const STORE_KEY = 'syntaxstack.misaki.chat';
const REVIEW_KEY = 'syntaxstack.misaki.review';
const REVIEW_QUESTION = 'Mình đã làm đúng và sai ở đâu trong bộ câu đố này?';
const FOLLOW_UP_QUESTION = 'Cho mình một câu hỏi tiếp theo cùng chủ đề, chỉ đổi một chi tiết nhé.';
const MAX_REVIEW_ATTEMPTS = 8;
const MAX_INPUT = 500; // API: 1 to 500 characters per message
const MAX_MESSAGES = 12; // API: 1 to 12 messages per request
const MAX_KEPT = 60;
const LEVELS = ['beginner', 'intermediate', 'advanced'];

const GREETING = 'Chào bạn! Hôm nay bạn đang vướng chỗ nào?';
const CHIPS = ['Mình hay sai vòng lặp', 'Mình thấy chán', 'Tạo câu đố cho mình', 'Nên chơi gì tiếp?'];
const DISCLAIMER = 'Do AI tạo, có thể chưa chính xác. Câu đố Misaki viết luôn được hệ thống kiểm chứng.';
const SAY = {
  offline: 'Mình đang mất kết nối một chút. Bạn gửi lại giúp mình nhé?',
  puzzleFail: 'Mình chưa viết được câu đố lúc này. Bạn thử lại sau nhé.',
  puzzleFast: 'Bạn nhờ mình hơi nhanh đó. Đợi một lát rồi nhờ mình lần nữa nhé.',
  puzzleNote: 'Câu đố của bạn đây. Vào giải thử nhé!',
};

let nav = { show: () => {}, home: () => {}, level: () => 'beginner', run: {} };
let ui = null; // DOM nodes, built once
let stage = null;
let msgs = null; // [{ role: 'misaki' | 'user', text, mood?, action?, local? }]
let busy = false;
let onScreen = false; // the stage is in view (the screen is open)
let soloed = false; // the learner hid the stage panel
let review = loadReview();

export function initMisakiChat(n) {
  nav = { ...nav, ...n, run: { ...(n.run || {}) } };
}

// ---- actions: whitelisted shapes (docs/misaki-chat.md section 2); anything else is dropped ----------------------------
const isInt = (v) => Number.isInteger(v);
export function cleanAction(a) {
  if (!a || typeof a !== 'object') return null;
  switch (a.type) {
    case 'rescue': {
      const focus = a.focus_topic || null;
      if (!['rescue', 'practice'].includes(a.mode) || !LEVELS.includes(a.level) || (focus && !TOPICS.includes(focus))) return null;
      return { type: 'rescue', mode: a.mode, level: a.level, focus_topic: focus };
    }
    case 'rows':
      return typeof a.level_id === 'string' && /^[A-Za-z0-9_-]{1,32}$/.test(a.level_id) ? { type: 'rows', level_id: a.level_id } : null;
    case 'practice_tray':
    case 'skills':
      return { type: a.type };
    case 'pvp_training':
      return isInt(a.misaki) && a.misaki >= 1 && a.misaki <= 4 ? { type: 'pvp_training', misaki: a.misaki } : null;
    case 'make_puzzle': {
      const idea = typeof a.idea === 'string' ? a.idea.slice(0, 200) : '';
      return TOPICS.includes(a.topic) ? { type: 'make_puzzle', topic: a.topic, idea } : null;
    }
    default:
      return null;
  }
}

function actionLabel(a) {
  switch (a.type) {
    case 'rescue':
      if (a.mode === 'rescue') return 'Chơi Code Rescue';
      return a.focus_topic ? `Luyện tập: ${TOPIC_NAMES[a.focus_topic]}` : 'Luyện tập Code Rescue';
    case 'rows': {
      const n = /^r(\d+)$/.exec(a.level_id);
      return n ? `Chơi Syntax Rows · Màn ${n[1]}` : 'Chơi Syntax Rows';
    }
    case 'practice_tray': return 'Luyện theo lỗi';
    case 'skills': return 'Mở bản đồ kỹ năng';
    case 'pvp_training': return `Luyện tập với ${misakiTitle(a.misaki)}`;
    default: return 'Tạo câu đố';
  }
}

// ---- history -----------------------------------------------------------------------------------------------------
const greeting = () => ({ role: 'misaki', text: GREETING, mood: 'happy', local: true });

function loadReview() {
  try {
    const saved = JSON.parse(sessionStorage.getItem(REVIEW_KEY));
    if (typeof saved?.set_id === 'string' && Array.isArray(saved.attempts)) return saved;
  } catch {
    /* the review is optional */
  }
  return null;
}

function saveReview(value) {
  review = value;
  try {
    if (value) sessionStorage.setItem(REVIEW_KEY, JSON.stringify(value));
    else sessionStorage.removeItem(REVIEW_KEY);
  } catch {
    /* keep the review in memory when storage is blocked */
  }
}

function recordAttempt(setId, puzzleId, answer, result) {
  const attempts = review?.set_id === setId ? review.attempts : [];
  const last = attempts.filter((entry) => entry.puzzle_id === puzzleId).at(-1);
  const recent = attempts.filter((entry) => entry.puzzle_id !== puzzleId || entry === last);
  saveReview({ set_id: setId, ready: review?.set_id === setId && review.ready || result?.correct || answer.reveal,
    attempts: [...recent, { puzzle_id: puzzleId, ...answer }].slice(-MAX_REVIEW_ATTEMPTS) });
}

function load() {
  try {
    const raw = JSON.parse(sessionStorage.getItem(STORE_KEY));
    if (Array.isArray(raw) && raw.length) {
      return raw
        .filter((m) => m && (m.role === 'user' || m.role === 'misaki') && typeof m.text === 'string' && m.text)
        .map((m) => ({ role: m.role, text: m.text.slice(0, 700), mood: m.mood, action: cleanAction(m.action), local: !!m.local }))
        .slice(-MAX_KEPT);
    }
  } catch {
    /* storage blocked or corrupt: start fresh */
  }
  return null;
}

function save() {
  try {
    sessionStorage.setItem(STORE_KEY, JSON.stringify(msgs.slice(-MAX_KEPT)));
  } catch {
    /* storage blocked: the history lives on in memory */
  }
}

/** The request body's messages: the last 12 that were really exchanged (local apologies are skipped). */
function payload() {
  const sent = msgs.filter((m) => !m.local || m.role === 'user' || m.text === GREETING);
  return sent.slice(-MAX_MESSAGES).map((m) => ({ role: m.role, text: m.text.slice(0, MAX_INPUT) }));
}

// ---- DOM ---------------------------------------------------------------------------------------------------------
const head = () => el('div', { class: 'tutor-head' }, misakiAvatar({ cls: 'tutor-badge' }),
  el('span', { class: 'tutor-label', text: 'MISAKI' }));

function actionKey(action) {
  const k = keycap({ tag: 'button', topic: 'neutral', legend: actionLabel(action), legendClass: 'kb-label', variant: 'btn', enter: true, cls: 'mk-action' });
  k.type = 'button';
  k.addEventListener('click', () => runAction(action, k));
  return k;
}

function rowFor(m) {
  if (m.role === 'user') {
    const bubble = keycap({ topic: 'neutral', legend: '', legendClass: 'mk-me-text', cls: 'mk-bubble' });
    bubble.querySelector('.mk-me-text').textContent = m.text;
    return el('li', { class: 'mk-row mk-row-me' }, bubble);
  }
  return el('li', { class: 'mk-row mk-row-ai' },
    el('div', { class: 'tutor mk-msg' }, head(), el('p', { class: 'tutor-body' }, richText(m.text))),
    m.action ? actionKey(m.action) : null);
}

function chipsRow() {
  const row = el('li', { class: 'mk-row mk-row-chips', dataset: { chips: '' } },
    el('div', { class: 'mk-chips', role: 'group', 'aria-label': 'Gợi ý câu hỏi' }));
  for (const text of CHIPS) {
    const c = keycap({ tag: 'button', topic: 'neutral', legend: text, legendClass: 'kb-label', variant: 'btn', cls: 'mk-chip' });
    c.type = 'button';
    c.addEventListener('click', () => send(text));
    row.firstChild.append(c);
  }
  return row;
}

function typingRow(text) {
  return el('li', { class: 'mk-row mk-row-ai', dataset: { typing: '' } },
    el('div', { class: 'tutor mk-msg' }, head(),
      el('p', { class: 'tutor-body tutor-loading' }, text, el('span', { class: 'tutor-dots', 'aria-hidden': 'true' }, el('i'), el('i'), el('i')))));
}

function scrollToEnd(smooth = true) {
  const w = ui.scroller;
  w.scrollTo({ top: w.scrollHeight, behavior: smooth && !reducedMotion() ? 'smooth' : 'auto' });
}

function renderAll() {
  ui.log.replaceChildren(...msgs.map(rowFor));
  if (!msgs.some((m) => m.role === 'user')) ui.log.children[0]?.after(chipsRow());
  scrollToEnd(false);
}

function append(m) {
  msgs.push(m);
  save();
  ui.log.querySelector('[data-chips]')?.remove();
  ui.log.append(rowFor(m));
  scrollToEnd();
}

function setBusy(on) {
  busy = on;
  ui.send.disabled = on;
  ui.followUp.hidden = !review?.ready;
  ui.followUp.disabled = on;
  ui.root.classList.toggle('is-busy', on);
  ui.log.setAttribute('aria-busy', on ? 'true' : 'false');
}

function typing(text) {
  const row = typingRow(text);
  ui.log.append(row);
  scrollToEnd();
  return row;
}

function setMood(m) {
  stage?.setMood(m || 'neutral');
}

// ---- chat --------------------------------------------------------------------------------------------------------
async function send(raw, puzzleRequest) {
  const text = String(raw || '').trim().slice(0, MAX_INPUT);
  if (!text || busy) return;
  const previous = msgs.at(-1);
  append({ role: 'user', text });
  ui.input.value = '';
  grow();
  ui.input.focus({ preventScroll: true });
  setBusy(true);
  const wait = typing('Misaki đang nghĩ');
  setMood('loading');
  let reply;
  try {
    const context = { level: nav.level(), weak_topics: store.weakTopics(TOPICS, 4) };
    if (review?.attempts.length) context.puzzle_review = { set_id: review.set_id, attempts: review.attempts };
    if (puzzleRequest) context.puzzle_request = puzzleRequest;
    if (previous?.role === 'misaki' && previous.action) context.previous_action = previous.action;
    reply = await api.misakiChat({ messages: payload(), context });
  } catch {
    reply = { text: SAY.offline, mood: 'worried', action: null, local: true };
  }
  wait.remove();
  const text2 = typeof reply?.text === 'string' && reply.text.trim() ? reply.text.trim().slice(0, 700) : SAY.offline;
  append({ role: 'misaki', text: text2, mood: reply?.mood, action: cleanAction(reply?.action), local: !!reply?.local || text2 === SAY.offline });
  setMood(reply?.mood);
  setBusy(false);
}

async function runAction(a, key) {
  if (busy) return;
  if (a.type === 'make_puzzle') return makePuzzle(a, key);
  try {
    await nav.run[a.type]?.(a);
  } catch (e) {
    toast(e.message);
  }
}

async function makePuzzle(a, key) {
  setBusy(true);
  key.disabled = true;
  const wait = typing('Misaki đang viết câu đố…');
  setMood('loading');
  let res = null;
  let status = 0;
  try {
    res = await api.misakiPuzzle({ topic: a.topic, idea: a.idea || '', level: nav.level() });
    if (!Array.isArray(res?.set?.puzzles) || !res.set.puzzles.length) res = null;
  } catch (e) {
    status = e.status || 0;
  }
  wait.remove();
  key.disabled = false;
  if (!res) {
    // her own words; the same button stays under the apology so the learner can try again
    append({ role: 'misaki', text: status === 429 ? SAY.puzzleFast : SAY.puzzleFail, mood: status === 429 ? 'shy' : 'sad', action: a, local: true });
    setMood(status === 429 ? 'shy' : 'sad');
    setBusy(false);
    return;
  }
  const note = typeof res.note === 'string' && res.note.trim() ? res.note.trim().slice(0, 300) : SAY.puzzleNote;
  append({ role: 'misaki', text: note, mood: 'happy', local: true });
  setMood('happy');
  setBusy(false);
  if (ui.root.hidden) return; // the learner left while she was writing: the note waits in the chat
  openCustom({ preset: {
    set: res.set, note, back: openMisakiChat, backLabel: 'Về cuộc trò chuyện',
    onAttempt: (id, answer, result) => recordAttempt(res.set.id, id, answer, result),
    onReview: () => {
      openMisakiChat();
      send(t(REVIEW_QUESTION), 'review');
    },
  } });
}

// ---- composer ----------------------------------------------------------------------------------------------------
function grow() {
  const t = ui.input;
  t.style.height = 'auto';
  t.style.height = Math.min(t.scrollHeight, 132) + 'px';
}

function newChat() {
  if (busy) return;
  msgs = [greeting()];
  saveReview(null);
  setBusy(false);
  save();
  renderAll();
  setMood('happy');
  ui.input.focus({ preventScroll: true });
}

function build() {
  const input = el('textarea', {
    id: 'mk-input', class: 'mk-input', rows: 1, maxlength: MAX_INPUT, autocomplete: 'off', enterkeyhint: 'send',
    'aria-label': 'Tin nhắn cho Misaki', placeholder: 'Nhắn cho Misaki…',
  });
  const send_ = keycap({ tag: 'button', topic: 'neutral', legend: 'Gửi', legendClass: 'kb-label', variant: 'btn', enter: true, cls: 'mk-send' });
  send_.type = 'submit';
  const form = el('form', { class: 'mk-composer', novalidate: true }, input, send_);
  form.addEventListener('submit', (e) => {
    e.preventDefault();
    send(input.value);
  });
  input.addEventListener('input', grow);
  input.addEventListener('keydown', (e) => {
    // Enter sends, Shift+Enter is a new line (not while an input method is composing)
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing && e.keyCode !== 229) {
      e.preventDefault();
      form.requestSubmit();
    }
  });

  const bar = titleBar({ file: 'misaki.chat', meta: '' });
  bar.querySelector('.ed-tab').style.setProperty('--accent', 'var(--mustard)');
  const fresh = el('button', { class: 'btn mk-new', type: 'button', text: 'Cuộc trò chuyện mới' });
  fresh.addEventListener('click', newChat);
  // hide / show Misaki's stage panel: a small keycap icon button, pressed while she is hidden
  const toggle = keycap({ tag: 'button', topic: 'neutral', legend: '', legendClass: 'mk-toggle-in', cls: 'mk-toggle' });
  toggle.type = 'button';
  toggle.setAttribute('aria-controls', 'mk-stage');
  toggle.querySelector('.mk-toggle-in').append(icon('panel-left', { size: 16 }), el('span', { class: 'mk-toggle-t' }));
  toggle.addEventListener('click', () => setSolo(!soloed));
  bar.querySelector('.ed-meta').replaceWith(el('div', { class: 'mk-bar-r' }, fresh, toggle));

  const log = el('ol', { class: 'mk-log', role: 'log', 'aria-live': 'polite', 'aria-relevant': 'additions', 'aria-label': 'Cuộc trò chuyện với Misaki' });
  const followUp = el('button', { class: 'btn', type: 'button', text: 'Thử câu hỏi tiếp theo', hidden: true,
    onclick: () => send(t(FOLLOW_UP_QUESTION), 'follow_up') });
  const scroller = el('div', { class: 'mk-scroll' }, log, followUp, el('p', { class: 'tutor-foot mk-foot-ai', text: DISCLAIMER }));
  const win = el('div', { class: 'editor mk-win' }, bar, scroller, form);
  $('mk-chat').replaceChildren(win);
  return { root: $('screen-misaki'), log, scroller, input, send: send_, toggle, followUp };
}

// ---- hide / show the stage ----------------------------------------------------------------------------------------
/** The WebGL loop only runs while the stage is on screen: the screen is open and the panel is not hidden. */
function syncStage() {
  if (!stage) return;
  if (onScreen && !soloed) stage.resume();
  else stage.pause();
}

function setSolo(hidden, { save = true } = {}) {
  soloed = hidden;
  ui.root.classList.toggle('is-solo', hidden);
  $('mk-stage').inert = hidden; // out of the tab order and the accessibility tree while collapsed
  ui.toggle.setAttribute('aria-pressed', hidden ? 'true' : 'false');
  const label = hidden ? 'Hiện Misaki' : 'Ẩn Misaki';
  ui.toggle.setAttribute('aria-label', label);
  ui.toggle.title = label;
  ui.toggle.querySelector('.mk-toggle-t').textContent = label;
  if (save) store.saveMisakiStageHidden(hidden);
  syncStage();
}

// ---- screen ------------------------------------------------------------------------------------------------------
export function openMisakiChat() {
  nav.show('screen-misaki');
  showStrip(true, { back: nav.home, backLabel: 'Về màn hình chính' });
  setMode('TRÒ CHUYỆN VỚI MISAKI');
  setStreak(null);
  if (!ui) {
    ui = build();
    $('mk-plate').replaceChildren(keycap({ topic: 'conditions', legend: 'MISAKI', legendClass: 'kb-label', cls: 'mk-plate-key' }));
    stage = mountStage($('mk-view'), { isPhone: () => !matchMedia('(min-width: 900px)').matches, bodySwitch: $('mk-body') });
    // no WebGL frames while the screen is hidden
    new IntersectionObserver(([e]) => {
      onScreen = e.isIntersecting || !ui.root.hidden;
      syncStage();
    }).observe($('mk-panel'));
    setSolo(store.loadMisakiStageHidden(), { save: false });
    stage.ready.then(syncStage); // a model that finishes loading while the panel is hidden must not start rendering
  }
  onScreen = true;
  syncStage();
  msgs = msgs || load() || [greeting()];
  renderAll();
  setBusy(busy);
  setMood(busy ? 'loading' : [...msgs].reverse().find((m) => m.role === 'misaki')?.mood);
  $('mk-title').focus({ preventScroll: true });
}
