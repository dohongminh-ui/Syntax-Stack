// Skill map ("Bản đồ kỹ năng"): 4 topics x 4 puzzle types laid out as a keyboard section.
// Fully client-side: reads the outcomes puzzle-modal.js records in storage. No network except the optional Syntax Rows stars.
import * as api from './api.js';
import * as store from './storage.js';
import * as R from './rows-game.js';
import { TOPICS, TOPIC_NAMES, TOPIC_GLYPH, PUZZLE_TYPES, TYPE_NAMES, TYPE_SHORT } from './pieces.js';
import { el, anim, EASE } from './ui.js';
import { icon } from './icons.js';
import { keycap } from './keycap.js';
import { showStrip, setMode, setStreak } from './strip.js';

const $ = (id) => document.getElementById(id);
let nav = { show: () => {}, home: () => {}, practice: () => {}, play: () => {} };
let sel = null; // { topic, type }
let view = null; // { map, levels }
let token = 0;

const LEVEL_WORD = ['chưa có dữ liệu', 'đang học', 'khá tốt', 'thành thạo'];
const TYPE_GLYPH = { fill_blank: '___', predict_output: '>>', parsons: '≡', find_bug: '!' };

export function initSkills(n) {
  nav = { ...nav, ...n };
}

/** 0 none, 1 learning, 2 getting there, 3 mastered. `a` = { attempts, correct, recent: boolean[] }. */
export function masteryOf(a) {
  if (!a || !a.attempts) return 0;
  const r = a.recent?.length ? a.recent : [];
  const rate = r.length ? r.filter(Boolean).length / r.length : 0;
  if (a.attempts >= 3 && rate >= 0.8 && r[r.length - 1]) return 3;
  if (rate < 0.5) return 1;
  return 2;
}

/** Folds the per-template records into one record per (topic, type). Recent outcomes are merged oldest-template-first. */
export function aggregate(skills) {
  const map = {};
  for (const t of TOPICS) for (const ty of PUZZLE_TYPES) map[`${t}:${ty}`] = { topic: t, type: ty, attempts: 0, correct: 0, recent: [], lastWrongPrompt: '', lastWrongAt: 0 };
  const entries = Object.values(skills || {})
    .filter((e) => e && map[`${e.topic}:${e.type}`])
    .sort((a, b) => (a.updatedAt || 0) - (b.updatedAt || 0));
  for (const e of entries) {
    const m = map[`${e.topic}:${e.type}`];
    m.attempts += e.attempts || 0;
    m.correct += e.correct || 0;
    m.recent.push(...(Array.isArray(e.recent) ? e.recent : []));
    if (e.lastWrongPrompt) {
      m.lastWrongPrompt = e.lastWrongPrompt;
      m.lastWrongAt = e.updatedAt || 0;
    }
  }
  for (const m of Object.values(map)) {
    m.recent = m.recent.slice(-6);
    m.level = masteryOf(m);
  }
  return map;
}

const aria = (m) => (m.attempts
  ? `${TOPIC_NAMES[m.topic]}, ${TYPE_NAMES[m.type]}: ${LEVEL_WORD[m.level]}, ${m.correct}/${m.attempts} đúng`
  : `${TOPIC_NAMES[m.topic]}, ${TYPE_NAMES[m.type]}: chưa có dữ liệu`);

function skillKey(m) {
  let k;
  if (m.level === 0) {
    k = el('button', { class: 'skill sk-0', type: 'button' }, el('span', { class: 'sk-plus', 'aria-hidden': 'true', text: '+' }));
  } else {
    k = keycap({ tag: 'button', topic: m.topic, legend: TYPE_GLYPH[m.type], cls: `skill sk-${m.level}${m.level === 3 ? ' is-lit is-pressed' : ''}` });
    k.type = 'button';
    if (m.level === 3) k.querySelector('.cap-top').append(el('span', { class: 'sk-badge', 'aria-hidden': 'true' }, icon('check', { size: 16 })));
  }
  k.dataset.key = `${m.topic}:${m.type}`;
  k.setAttribute('aria-label', aria(m));
  k.setAttribute('aria-controls', 'sk-detail');
  if (sel && sel.topic === m.topic && sel.type === m.type) {
    k.classList.add('sel');
    k.setAttribute('aria-current', 'true');
  }
  k.addEventListener('click', () => select(m.topic, m.type));
  return k;
}

function select(topic, type) {
  sel = { topic, type };
  for (const b of document.querySelectorAll('#sk-case .skill')) {
    const on = b.dataset.key === `${topic}:${type}`;
    b.classList.toggle('sel', on);
    if (on) b.setAttribute('aria-current', 'true');
    else b.removeAttribute('aria-current');
  }
  renderDetail();
}

function buildCase(map) {
  const grid = el('div', { class: 'sk-grid', role: 'group', 'aria-label': 'Bản đồ 16 kỹ năng: 4 chủ đề, mỗi chủ đề 4 dạng câu đố' });
  grid.append(el('span', { class: 'sk-corner', 'aria-hidden': 'true' }));
  for (const ty of PUZZLE_TYPES) {
    grid.append(el('span', { class: 'pv-label sk-colh', 'aria-hidden': 'true' },
      el('span', { class: 'full', text: TYPE_NAMES[ty] }), el('span', { class: 'short', text: TYPE_SHORT[ty] })));
  }
  for (const t of TOPICS) {
    const lab = keycap({ topic: t, legend: el('span', {}, el('span', { class: 'full', text: TOPIC_NAMES[t] }), el('span', { class: 'short', text: TOPIC_GLYPH[t] })), legendClass: 'sk-lab', cls: 'sk-labkey' });
    lab.setAttribute('aria-hidden', 'true');
    grid.append(lab);
    for (const ty of PUZZLE_TYPES) {
      const m = map[`${t}:${ty}`];
      grid.append(el('div', { class: 'sk-cell' }, skillKey(m),
        el('span', { class: 'sk-count', 'aria-hidden': 'true', text: m.attempts ? `${m.correct}/${m.attempts}` : '–' })));
    }
  }
  return grid;
}

function dots(recent) {
  const wrap = el('span', { class: 'sk-dots', role: 'img', 'aria-label': recent.length ? 'Gần đây, cũ đến mới: ' + recent.map((x) => (x ? 'đúng' : 'sai')).join(', ') : 'Chưa có lượt nào' });
  for (const ok of recent) wrap.append(el('i', { class: 'sk-dot ' + (ok ? 'ok' : 'bad'), 'aria-hidden': 'true' }, icon(ok ? 'check' : 'x', { size: 12 })));
  if (!recent.length) wrap.append(el('span', { class: 'sk-none', text: '–' }));
  return wrap;
}

function renderDetail() {
  const box = $('sk-detail');
  if (!sel || !view) {
    box.replaceChildren(el('p', { class: 'sk-hint', text: 'Chạm vào một phím để xem chi tiết kỹ năng.' }));
    return;
  }
  const m = view.map[`${sel.topic}:${sel.type}`];
  const pct = m.attempts ? Math.round((m.correct / m.attempts) * 100) : null;
  const practice = keycap({ tag: 'button', topic: 'neutral', legend: 'Luyện chủ đề này', legendClass: 'kb-label', variant: 'btn', enter: true });
  practice.type = 'button';
  practice.addEventListener('click', () => nav.practice(m.topic));
  box.replaceChildren(el('section', { class: 'sk-card t-' + m.topic, 'aria-label': `${TOPIC_NAMES[m.topic]}, ${TYPE_NAMES[m.type]}` },
    el('div', { class: 'sk-card-top' },
      el('span', { class: 'chip', text: TOPIC_NAMES[m.topic] }),
      el('h2', { class: 'sk-card-h', text: TYPE_NAMES[m.type] }),
      el('span', { class: 'sk-state l' + m.level, text: LEVEL_WORD[m.level] })),
    m.attempts
      ? el('dl', { class: 'receipt sk-stats' },
          el('div', {}, el('dt', { text: 'accuracy' }), el('dd', { text: pct + '%' })),
          el('div', {}, el('dt', { text: 'attempts' }), el('dd', { text: `${m.correct}/${m.attempts}` })),
          el('div', {}, el('dt', { text: 'recent' }), el('dd', {}, dots(m.recent))))
      : el('p', { class: 'cm', text: 'Chưa có lượt nào. Giải câu đố loại này trong Code Rescue để mở khóa phím.' }),
    m.lastWrongPrompt ? el('p', { class: 'cm sk-wrong' }, el('span', { class: 'sk-wrong-l', text: 'Lần sai gần nhất: ' }), m.lastWrongPrompt) : null,
    el('div', { class: 'sk-card-act' }, practice)));
}

function renderSummary(mastered, stars) {
  const p = $('sk-summary');
  p.replaceChildren(el('span', { class: 'stat' }, icon('check', { size: 14 }), el('b', { text: `${mastered}/16` }), ' kỹ năng thành thạo'));
  if (stars) p.append(el('span', { class: 'stat' }, icon('star', { size: 14, fill: true }), el('b', { text: `${stars.stars}/${stars.max}` }), ' sao Syntax Rows'));
}

/** opts.sample: skills object shown instead of storage (QA demo; nothing is saved). */
export function openSkills({ sample = null } = {}) {
  const mine = ++token;
  nav.show('screen-skills');
  showStrip(true, { back: nav.home, backLabel: 'Về màn hình chính' });
  setMode('BẢN ĐỒ KỸ NĂNG');
  setStreak(null);
  const map = aggregate(sample || store.loadSkills());
  view = { map };
  const all = Object.values(map);
  const mastered = all.filter((m) => m.level === 3).length;
  const seen = sample ? {} : store.loadSkillsSeen();
  const levels = Object.fromEntries(all.map((m) => [`${m.topic}:${m.type}`, m.level]));
  sel = null;

  $('sk-case').replaceChildren(buildCase(map));
  renderSummary(mastered, null);
  const empty = !all.some((m) => m.attempts);
  const slot = $('sk-empty');
  slot.hidden = !empty;
  if (empty) {
    const cta = keycap({ tag: 'button', topic: 'neutral', legend: 'Chơi Code Rescue', legendClass: 'kb-label', variant: 'btn', enter: true });
    cta.type = 'button';
    cta.addEventListener('click', () => nav.play());
    slot.replaceChildren(el('p', { class: 'sk-empty-t', text: 'Chưa có dữ liệu. Mỗi câu đố bạn giải trong Code Rescue sẽ bật sáng một phím trên bản đồ này.' }), cta);
  }
  renderDetail();
  $('sk-title').focus({ preventScroll: true });

  // Keys whose mastery rose since the last visit pop once (anim() already drops the transform under reduced motion).
  for (const b of document.querySelectorAll('#sk-case .skill')) {
    if ((levels[b.dataset.key] || 0) > (seen[b.dataset.key] || 0)) {
      anim(b, [
        { transform: 'scale(1)', filter: 'brightness(1)' },
        { transform: 'scale(1.18)', filter: 'brightness(1.35)', offset: 0.4 },
        { transform: 'scale(1)', filter: 'brightness(1)' },
      ], { duration: 460, easing: EASE.out });
    }
  }
  if (!sample) store.saveSkillsSeen(levels);

  // Syntax Rows stars: never block the screen on the network.
  api.rowsLevels().then((lv) => {
    if (mine !== token || $('screen-skills').hidden) return;
    renderSummary(mastered, R.totals(lv, store.loadRowsProgress()));
  }).catch(() => {});
}
