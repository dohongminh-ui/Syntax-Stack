// "Chat with Misaki" (docs/misaki-chat.md): the learner talks to the game's AI character, she answers in text and with
// her Live2D model (misaki-stage.js), and may propose ONE action as an Enter keycap under her bubble. An action never
// runs without a click. The validator decides, the AI explains: puzzles she makes go through the server's custom-set
// pipeline and are played in the custom-puzzle screen. History lives in this module and in sessionStorage.
import * as api from './api.js';
import * as store from './storage.js';
import { TOPICS, TOPIC_NAMES } from './pieces.js';
import { el, toast, reducedMotion, wait as delay } from './ui.js';
import { keycap } from './keycap.js';
import { icon } from './icons.js';
import { titleBar, richText } from './editor.js';
import { misakiAvatar, misakiTitle } from './misaki.js';
import { showStrip, setMode, setStreak } from './strip.js';
import { openCustom } from './custom.js';
import { mountStage } from './misaki-stage.js';
import { createVoicePlayer, voiceSupported } from './misaki-voice.js';
import { createFollowAlong } from './misaki-follow-along.js';
import {
  rehearsing, beginRehearsal, rehearsalReply, rehearsalPuzzleIdea, isRehearsalRecording, preloadRehearsalAudio,
} from './misaki-rehearsal.js';
import { isMuted, onMuteChange, prepareAudio } from './sound.js';
import { lang, t } from './i18n.js';

const $ = (id) => document.getElementById(id);
const chatKey = () => rehearsing ? 'syntaxstack.misaki.rehearsal.chat' : 'syntaxstack.misaki.chat';
const reviewKey = () => rehearsing ? 'syntaxstack.misaki.rehearsal.review' : 'syntaxstack.misaki.review';
const REVIEW_QUESTION = 'Mình đã làm đúng và sai ở đâu trong bộ câu đố này?';
const FOLLOW_UP_QUESTION = 'Cho mình một câu hỏi tiếp theo cùng chủ đề, chỉ đổi một chi tiết nhé.';
const MAX_REVIEW_ATTEMPTS = 8;
const MAX_INPUT = 500; // API: 1 to 500 characters per message
const MAX_MESSAGES = 12; // API: 1 to 12 messages per request
const MAX_KEPT = 60;
const VOICE_START_TIMEOUT_MS = 15000;
const REHEARSAL_THINK_MS = 1000;
const LEVELS = ['beginner', 'intermediate', 'advanced'];
const VOICE_LANGUAGES = ['vi', 'en', 'ja'];

const GREETINGS = {
  vi: 'Chào bạn! Hôm nay bạn đang vướng chỗ nào?',
  en: 'Hi! What are you stuck on today?',
};
const CHIPS = ['Mình hay sai vòng lặp', 'Mình thấy chán', 'Tạo câu đố cho mình', 'Nên chơi gì tiếp?'];
const DISCLAIMER = 'Do AI tạo, có thể chưa chính xác. Câu đố Misaki viết luôn được hệ thống kiểm chứng.';
const SAY = {
  vi: {
    offline: 'Mình đang mất kết nối một chút. Bạn gửi lại giúp mình nhé?',
    puzzleFail: 'Mình chưa viết được câu đố lúc này. Bạn thử lại sau nhé.',
    puzzleFast: 'Bạn nhờ mình hơi nhanh đó. Đợi một lát rồi nhờ mình lần nữa nhé.',
    puzzleNote: 'Câu đố của bạn đây. Vào giải thử nhé!',
  },
  en: {
    offline: 'I lost the connection for a moment. Could you send that again?',
    puzzleFail: 'I couldn’t make a puzzle right now. Try again in a bit.',
    puzzleFast: 'Give me a moment, then ask me again.',
    puzzleNote: 'Here’s your puzzle. Give it a try!',
  },
};

let nav = { show: () => {}, home: () => {}, level: () => 'beginner', run: {} };
let ui = null; // DOM nodes, built once
let stage = null;
let playbackScreen = null;
const voicePlayer = createVoicePlayer((sample) => stage?.setVoiceSampler(sample));
onMuteChange((muted) => {
  if (muted) voicePlayer.stop();
  else if (rehearsing && voiceSupported && ui && !ui.root.hidden) preloadRehearsalAudio();
  document.querySelectorAll('.mk-voice').forEach((button) => { button.disabled = muted; });
});
let msgs = null; // [{ role: 'misaki' | 'user', text, mood?, action?, local? }]
let busy = false;
let onScreen = false; // the stage is in view (the screen is open)
let soloed = false; // the learner hid the stage panel
let review = loadReview();
const savedLanguage = store.loadMisakiVoiceLanguage();
let voiceLanguage = VOICE_LANGUAGES.includes(savedLanguage) ? savedLanguage : lang();

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

function referralReply({ target, previous, playable }) {
  const english = lang() === 'en';
  let text = english
    ? `Level ${target.order} is locked. Finish Level ${previous.order} to unlock it.`
    : `Màn ${target.order} đang khóa. Hoàn thành Màn ${previous.order} để mở nhé.`;
  if (playable !== previous) {
    text += english ? ` You can start with Level ${playable.order}.` : ` Bạn có thể bắt đầu ở Màn ${playable.order}.`;
  }
  return { text, mood: 'happy', action: { type: 'rows', level_id: playable.id } };
}

// ---- history -----------------------------------------------------------------------------------------------------
const greeting = () => ({
  role: 'misaki', text: GREETINGS[lang()], language: lang(), mood: 'happy', local: true,
});

function loadReview() {
  try {
    const saved = JSON.parse(sessionStorage.getItem(reviewKey()));
    if (typeof saved?.set_id === 'string' && Array.isArray(saved.attempts)) return saved;
  } catch {
    /* the review is optional */
  }
  return null;
}

function saveReview(value) {
  review = value;
  try {
    if (value) sessionStorage.setItem(reviewKey(), JSON.stringify(value));
    else sessionStorage.removeItem(reviewKey());
  } catch {
    /* keep the review in memory when storage is blocked */
  }
}

function recordAttempt(setId, puzzleId, answer, result, prepared) {
  const attempts = review?.set_id === setId ? review.attempts : [];
  const last = attempts.filter((entry) => entry.puzzle_id === puzzleId).at(-1);
  const recent = attempts.filter((entry) => entry.puzzle_id !== puzzleId || entry === last);
  saveReview({ set_id: setId, prepared, ready: review?.set_id === setId && review.ready || result?.correct || answer.reveal,
    attempts: [...recent, { puzzle_id: puzzleId, ...answer }].slice(-MAX_REVIEW_ATTEMPTS) });
}

function load() {
  try {
    const raw = JSON.parse(sessionStorage.getItem(chatKey()));
    if (Array.isArray(raw) && raw.length) {
      return raw
        .filter((m) => m && (m.role === 'user' || m.role === 'misaki') && typeof m.text === 'string' && m.text)
        .map((m) => ({ role: m.role, text: m.text.slice(0, 700), mood: m.mood, action: cleanAction(m.action),
          voice: m.voice, local: !!m.local, language: VOICE_LANGUAGES.includes(m.language) ? m.language : null }))
        .slice(-MAX_KEPT);
    }
  } catch {
    /* storage blocked or corrupt: start fresh */
  }
  return null;
}

function save() {
  try {
    sessionStorage.setItem(chatKey(), JSON.stringify(msgs.slice(-MAX_KEPT)));
  } catch {
    /* storage blocked: the history lives on in memory */
  }
}

/** The request body's messages: the last 12 that were really exchanged (local apologies are skipped). */
function payload() {
  const sent = msgs.filter((m) => !m.local || m.role === 'user' || Object.values(GREETINGS).includes(m.text));
  return sent.slice(-MAX_MESSAGES).map((m) => ({ role: m.role, text: m.text.slice(0, MAX_INPUT) }));
}

// ---- DOM ---------------------------------------------------------------------------------------------------------
const head = (voiceButton) => el('div', { class: 'tutor-head' }, misakiAvatar({ cls: 'tutor-badge' }),
  el('span', { class: 'tutor-label', text: 'MISAKI' }), voiceButton);

function voiceKey({ voice, text }, screen = ui.root) {
  const recorded = isRehearsalRecording(voice?.recording);
  const ticketed = typeof voice?.ticket === 'string' && voice.expires * 1000 > Date.now();
  if (!voiceSupported || (!recorded && !ticketed)) return null;
  const follow = createFollowAlong(text, voice.transcript);
  const idleLabel = t('Nghe Misaki');
  const activeLabel = t('Dừng giọng Misaki');
  const button = el('button', { class: 'mk-voice', type: 'button', disabled: isMuted() });
  const setState = (active) => {
    if (!active) follow.stop();
    const label = active ? activeLabel : idleLabel;
    button.setAttribute('aria-label', label);
    button.title = label;
    button.replaceChildren(icon(active ? 'volume-x' : 'volume', { size: 16 }));
  };
  setState(false);
  button.addEventListener('click', () => {
    playbackScreen = screen;
    voicePlayer.toggle(voice, setState, follow.start, follow.align)
      .catch(() => toast(t('Giọng Misaki chưa sẵn sàng. Hãy thử lại.')));
  });
  const play = () => new Promise((resolve) => {
    playbackScreen = screen;
    voicePlayer.play(voice, (active) => {
      setState(active);
      if (!active) resolve();
    }, (buffer, elapsed) => {
      follow.start(buffer, elapsed);
      resolve();
    }, follow.align).then(resolve, resolve);
  });
  return { button, play, spans: follow.spans, recorded };
}

function canPlayVoice(screen) {
  return !screen.hidden && !document.hidden && !isMuted();
}

async function playVoice(voice) {
  let timer;
  await Promise.race([voice.play(), new Promise((resolve) => {
    timer = setTimeout(() => {
      voicePlayer.stop();
      resolve();
    }, voice.recorded ? 750 : VOICE_START_TIMEOUT_MS);
  })]);
  clearTimeout(timer);
  voice.button.disabled = isMuted();
}

function actionKey(action) {
  const k = keycap({ tag: 'button', topic: 'neutral', legend: actionLabel(action), legendClass: 'kb-label', variant: 'btn', enter: true, cls: 'mk-action' });
  k.type = 'button';
  k.addEventListener('click', () => runAction(action, k));
  return k;
}

function rowFor(m, voice = voiceKey(m)) {
  if (m.role === 'user') {
    const bubble = keycap({ topic: 'neutral', legend: '', legendClass: 'mk-me-text', cls: 'mk-bubble' });
    bubble.querySelector('.mk-me-text').textContent = m.text;
    return el('li', { class: 'mk-row mk-row-me' }, bubble);
  }
  return el('li', { class: 'mk-row mk-row-ai' },
    el('div', { class: 'tutor mk-msg' }, head(voice?.button),
      el('p', { class: 'tutor-body', lang: m.language, translate: m.language && 'no' },
        voice?.spans ?? richText(m.text))),
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
  ui.log.replaceChildren(...msgs.map((message) => rowFor(message)));
  if (!msgs.some((m) => m.role === 'user')) ui.log.children[0]?.after(chipsRow());
  scrollToEnd(false);
}

function append(m, row = rowFor(m)) {
  msgs.push(m);
  save();
  ui.log.querySelector('[data-chips]')?.remove();
  ui.log.append(row);
  scrollToEnd();
}

function setBusy(on) {
  busy = on;
  ui.send.disabled = on;
  ui.language.disabled = on;
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

function finishRehearsalThinking(startedAt) {
  const remaining = REHEARSAL_THINK_MS - (performance.now() - startedAt);
  return remaining > 0 ? delay(remaining) : undefined;
}

// ---- chat --------------------------------------------------------------------------------------------------------
async function send(raw, puzzleRequest) {
  const text = String(raw || '').trim().slice(0, MAX_INPUT);
  if (!text || busy) return;
  voicePlayer.stop();
  const requestVoice = voiceSupported && !isMuted();
  // Use the send gesture to unlock audio, before the reply arrives.
  if (requestVoice) prepareAudio();
  const previous = msgs.at(-1);
  append({ role: 'user', text });
  ui.input.value = '';
  grow();
  ui.input.focus({ preventScroll: true });
  setBusy(true);
  let wait = typing('Misaki đang nghĩ');
  setMood('loading');
  const startedAt = performance.now();
  const language = lang();
  const offline = SAY[language].offline;
  const preparedTurn = puzzleRequest ? null : rehearsalReply(text);
  const preparedReview = rehearsing && review?.prepared && puzzleRequest === 'review';
  let reply;
  try {
    reply = preparedTurn;
    if (reply?.action?.type === 'rows') {
      const referral = await nav.lockedLevelReferral(reply.action.level_id);
      if (referral) reply = referralReply(referral);
    }
    if (!reply) {
      const liveVoice = requestVoice && !preparedReview;
      const rowsCompleted = Object.entries(store.loadRowsProgress())
        .filter(([, result]) => result?.stars >= 1)
        .map(([id]) => id);
      const context = { level: nav.level(), weak_topics: store.weakTopics(TOPICS, 4), rows_completed: rowsCompleted };
      if (review?.attempts.length) context.puzzle_review = { set_id: review.set_id, attempts: review.attempts };
      if (puzzleRequest) context.puzzle_request = puzzleRequest;
      if (previous?.role === 'misaki' && previous.action) context.previous_action = previous.action;
      reply = await api.misakiChat({
        messages: payload(), context, rehearsal: preparedReview || undefined,
        voice: liveVoice, voice_language: liveVoice ? (rehearsing ? 'en' : voiceLanguage) : undefined,
      });
    }
  } catch {
    reply = { text: offline, mood: 'worried', action: null, local: true };
  }
  if (preparedTurn || preparedReview) await finishRehearsalThinking(startedAt);
  const text2 = typeof reply?.text === 'string' && reply.text.trim() ? reply.text.trim().slice(0, 700) : offline;
  const message = { role: 'misaki', text: text2, mood: reply?.mood, action: cleanAction(reply?.action),
    voice: reply?.recording ? { recording: reply.recording } : reply?.voice, language, local: !!reply?.local || text2 === offline };
  const voice = voiceKey(message);
  if (voice && canPlayVoice(ui.root)) {
    const preparing = typingRow('Misaki đang chuẩn bị giọng nói');
    wait.replaceWith(preparing);
    wait = preparing;
    await playVoice(voice);
  }
  wait.remove();
  append(message, rowFor(message, voice));
  setMood(reply?.mood);
  setBusy(false);
}

async function runAction(a, key) {
  if (busy) return;
  voicePlayer.stop();
  if (a.type === 'make_puzzle') return makePuzzle(a, key);
  try {
    if (a.type === 'rows') {
      const referral = await nav.lockedLevelReferral(a.level_id);
      if (busy || ui.root.hidden) return;
      if (referral) {
        append({ role: 'misaki', ...referralReply(referral), language: lang() });
        setMood('happy');
        return;
      }
    }
    await nav.run[a.type]?.(a);
  } catch (e) {
    toast(e.message);
  }
}

async function makePuzzle(a, key) {
  const requestVoice = voiceSupported && !isMuted();
  const prepared = rehearsing && a.idea === rehearsalPuzzleIdea;
  const liveVoice = requestVoice && !prepared;
  if (requestVoice) prepareAudio();
  setBusy(true);
  key.disabled = true;
  const wait = typing('Misaki đang viết câu đố…');
  setMood('loading');
  const startedAt = performance.now();
  const language = lang();
  const lines = SAY[language];
  let res = null;
  let status = 0;
  try {
    res = await api.misakiPuzzle({ topic: a.topic, idea: a.idea || '', level: nav.level(),
      rehearsal: prepared || undefined, voice: liveVoice, voice_language: liveVoice ? (rehearsing ? 'en' : voiceLanguage) : undefined });
    if (!Array.isArray(res?.set?.puzzles) || !res.set.puzzles.length) res = null;
  } catch (e) {
    status = e.status || 0;
  }
  if (prepared) await finishRehearsalThinking(startedAt);
  wait.remove();
  key.disabled = false;
  if (!res) {
    // her own words; the same button stays under the apology so the learner can try again
    append({ role: 'misaki', text: status === 429 ? lines.puzzleFast : lines.puzzleFail, mood: status === 429 ? 'shy' : 'sad',
      action: a, local: true, language });
    setMood(status === 429 ? 'shy' : 'sad');
    setBusy(false);
    return;
  }
  const note = typeof res.note === 'string' && res.note.trim() ? res.note.trim().slice(0, 300) : lines.puzzleNote;
  const message = { role: 'misaki', text: note, mood: 'happy', local: true, language,
    voice: res.recording ? { recording: res.recording } : res.voice };
  append(message);
  setMood('happy');
  setBusy(false);
  if (ui.root.hidden) return; // the learner left while she was writing: the note waits in the chat
  const puzzleScreen = $('screen-custom');
  const voice = voiceKey(message, puzzleScreen);
  const noteContent = voice && el('span', { class: 'cu-voiced-note' });
  const reveal = () => noteContent.replaceChildren(
    el('span', { lang: language, translate: 'no' }, voice.spans), voice.button);
  const autoplay = voice && !document.hidden && !isMuted();
  if (autoplay) noteContent.textContent = 'Misaki đang chuẩn bị giọng nói';
  else if (voice) reveal();
  openCustom({ preset: {
    set: res.set, note, noteContent, back: openMisakiChat, backLabel: 'Về cuộc trò chuyện',
    onAttempt: (id, answer, result) => recordAttempt(res.set.id, id, answer, result, prepared),
    onReview: () => {
      openMisakiChat();
      send(t(REVIEW_QUESTION), 'review');
    },
  } });
  if (autoplay) {
    await playVoice(voice);
    reveal();
  }
}

// ---- composer ----------------------------------------------------------------------------------------------------
function grow() {
  const t = ui.input;
  t.style.height = 'auto';
  t.style.height = Math.min(t.scrollHeight, 132) + 'px';
}

function newChat() {
  if (busy) return;
  voicePlayer.stop();
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
  const voiceLabel = 'Ngôn ngữ giọng nói của Misaki';
  const language = el('select', { class: 'mk-language', 'aria-label': voiceLabel },
    VOICE_LANGUAGES.map((code) => el('option', { value: code, text: code.toUpperCase() })));
  language.value = voiceLanguage;
  language.addEventListener('change', () => {
    voiceLanguage = language.value;
    store.saveMisakiVoiceLanguage(voiceLanguage);
    voicePlayer.stop();
  });
  const voiceControl = el('label', { class: 'mk-voice-language', title: voiceLabel },
    icon('volume', { size: 14 }), language);
  const fresh = el('button', { class: 'btn mk-new', type: 'button', text: 'Cuộc trò chuyện mới' });
  fresh.addEventListener('click', newChat);
  // hide / show Misaki's stage panel: a small keycap icon button, pressed while she is hidden
  const toggle = keycap({ tag: 'button', topic: 'neutral', legend: '', legendClass: 'mk-toggle-in', cls: 'mk-toggle' });
  toggle.type = 'button';
  toggle.setAttribute('aria-controls', 'mk-stage');
  toggle.querySelector('.mk-toggle-in').append(icon('panel-left', { size: 16 }), el('span', { class: 'mk-toggle-t' }));
  toggle.addEventListener('click', () => setSolo(!soloed));
  bar.querySelector('.ed-meta').replaceWith(el('div', { class: 'mk-bar-r' }, voiceControl, fresh, toggle));

  const log = el('ol', { class: 'mk-log', role: 'log', 'aria-live': 'polite', 'aria-relevant': 'additions', 'aria-label': 'Cuộc trò chuyện với Misaki' });
  const followUp = el('button', { class: 'btn', type: 'button', text: 'Thử câu hỏi tiếp theo', hidden: true,
    onclick: () => send(t(FOLLOW_UP_QUESTION), 'follow_up') });
  const scroller = el('div', { class: 'mk-scroll' }, log, followUp, el('p', { class: 'tutor-foot mk-foot-ai', text: DISCLAIMER }));
  const win = el('div', { class: 'editor mk-win' }, bar, scroller, form);
  $('mk-chat').replaceChildren(win);
  return { root: $('screen-misaki'), log, scroller, input, send: send_, toggle, followUp, language, voiceControl };
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
export function openMisakiRehearsal() {
  if (busy) return;
  if (!rehearsing) {
    beginRehearsal();
    msgs = null;
    review = loadReview();
  }
  openMisakiChat();
}

export function openMisakiChat() {
  nav.show('screen-misaki');
  if (rehearsing && voiceSupported && !isMuted()) preloadRehearsalAudio();
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
    const voiceVisibility = new MutationObserver(() => {
      if (playbackScreen?.hidden) voicePlayer.stop();
    });
    voiceVisibility.observe(ui.root, { attributeFilter: ['hidden'] });
    voiceVisibility.observe($('screen-custom'), { attributeFilter: ['hidden'] });
    document.addEventListener('visibilitychange', () => {
      if (document.hidden) voicePlayer.stop();
    });
    setSolo(store.loadMisakiStageHidden(), { save: false });
    stage.ready.then(syncStage); // a model that finishes loading while the panel is hidden must not start rendering
  }
  ui.voiceControl.hidden = rehearsing;
  onScreen = true;
  syncStage();
  if (!msgs) {
    msgs = load();
    if (!msgs?.some((m) => m.role === 'user')) msgs = [greeting()];
  }
  renderAll();
  setBusy(busy);
  setMood(busy ? 'loading' : [...msgs].reverse().find((m) => m.role === 'misaki')?.mood);
  $('mk-title').focus({ preventScroll: true });
}
