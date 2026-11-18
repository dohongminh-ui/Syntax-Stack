// Leaderboard screen: verified ranked runs only. Period tabs, level keycaps, top 50, the player's own row.
// Presentation + thin API glue; ranks and scores come from the server.
import * as api from './api.js';
import { el, toast } from './ui.js';
import { icon } from './icons.js';
import { keycap } from './keycap.js';
import { showStrip, setMode, setStreak } from './strip.js';
import { askNickname, getDeviceId, getNickname } from './identity.js';
import { rankMark, fmtScore } from './rank-ui.js';

const $ = (id) => document.getElementById(id);
let nav = { show: () => {}, home: () => {}, level: () => 'beginner', playRun: () => {} };
let token = 0;
let view = { level: 'beginner', period: 'day' };

export function initLeaderboard(n) {
  nav = { ...nav, ...n };
  $('btn-leaderboard').addEventListener('click', () => openLeaderboard());
  for (const name of ['lb-period', 'lb-level']) {
    document.querySelectorAll(`input[name=${name}]`).forEach((i) =>
      i.addEventListener('change', () => {
        view[name === 'lb-period' ? 'period' : 'level'] = i.value;
        load();
      }),
    );
  }
  $('lb-nick-btn').addEventListener('click', async () => {
    const name = await askNickname({ title: getNickname() ? 'Đổi tên' : 'Chọn tên', text: 'Tên mới áp dụng cho các ván xếp hạng tiếp theo. Tên được tạo ngẫu nhiên để bảng xếp hạng luôn thân thiện.', confirmLabel: 'Dùng tên này' });
    if (name) {
      paintNick();
      toast('Đã lưu tên.');
      $('lb-nick-btn').focus({ preventScroll: true });
    }
  });
}

function paintNick() {
  const n = getNickname();
  $('lb-nick').replaceChildren(n ? el('b', { text: n }) : el('span', { class: 'lb-nick-none', text: 'Chưa đặt' }));
  $('lb-nick-btn').textContent = n ? 'Đổi tên' : 'Chọn tên';
}

export function openLeaderboard({ level = null } = {}) {
  nav.show('screen-leaderboard');
  showStrip(true, { back: () => nav.home(), backLabel: 'Về màn hình chính' });
  setMode('BẢNG XẾP HẠNG');
  setStreak(null);
  view.level = level || nav.level();
  const lv = document.querySelector(`input[name=lb-level][value=${view.level}]`);
  if (lv) lv.checked = true;
  const pe = document.querySelector(`input[name=lb-period][value=${view.period}]`);
  if (pe) pe.checked = true;
  $('lb-mock').hidden = !api.isMock;
  paintNick();
  $('lb-title').focus({ preventScroll: true });
  load();
}

function playKey(label) {
  const k = keycap({ tag: 'button', topic: 'neutral', legend: label, legendClass: 'kb-label', variant: 'btn', enter: true });
  k.type = 'button';
  k.addEventListener('click', () => nav.playRun('ranked', view.level));
  return k;
}

function row(e, { you = false, pinned = false } = {}) {
  return el('li', { class: 'lb-row' + (you ? ' is-you' : '') + (pinned ? ' is-pinned' : ''), 'aria-current': you ? 'true' : false },
    el('span', { class: 'lb-rank' }, rankMark(e.rank)),
    el('span', { class: 'lb-name' }, el('span', { class: 'lb-nick-t', text: e.nickname }), you ? el('span', { class: 'lb-you', text: 'bạn' }) : null),
    el('span', { class: 'lb-locks', text: e.locks == null ? '' : `${e.locks} hàng` }),
    el('b', { class: 'lb-score', text: fmtScore(e.score) }));
}

async function load() {
  const mine = ++token;
  const box = $('lb-list');
  box.setAttribute('aria-busy', 'true');
  box.replaceChildren(el('p', { class: 'tp-none lb-loading', role: 'status' }, el('i', { class: 'led on rk-pulse', style: { '--c': 'var(--warn)' } }), 'Đang tải bảng xếp hạng…'));
  let data;
  try {
    data = await api.leaderboard({ level: view.level, period: view.period, device_id: getDeviceId() });
  } catch (e) {
    if (mine !== token) return;
    box.removeAttribute('aria-busy');
    const retry = el('button', { class: 'btn', type: 'button', text: 'Thử lại', onclick: load });
    box.replaceChildren(el('p', { class: 'rs-error', role: 'alert' }, icon('alert', { size: 16 }), 'Không tải được bảng xếp hạng: ' + e.message), retry);
    return;
  }
  if (mine !== token) return;
  box.removeAttribute('aria-busy');
  const entries = data.entries || [];
  if (!entries.length) {
    box.replaceChildren(el('div', { class: 'lb-empty' },
      el('p', { class: 'lb-empty-t', text: 'Chưa có ai trên bảng này. Hãy là người đầu tiên.' }),
      playKey('Chơi xếp hạng')));
    return;
  }
  const you = data.you || null;
  const inList = you && entries.some((e) => e.rank === you.rank);
  const list = el('ol', { class: 'lb-list', 'aria-label': 'Top 50' },
    ...entries.map((e) => row(e, { you: !!you && e.rank === you.rank })));
  const kids = [list];
  if (you && !inList) {
    kids.push(el('div', { class: 'lb-pin' },
      el('span', { class: 'lb-gap', 'aria-hidden': 'true', text: '⋯' }),
      el('ol', { 'aria-label': 'Hạng của bạn' }, row({ rank: you.rank, nickname: getNickname() || 'Bạn', score: you.score, locks: null }, { you: true, pinned: true }))));
  }
  box.replaceChildren(...kids);
}
