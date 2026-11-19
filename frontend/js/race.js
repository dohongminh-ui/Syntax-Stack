// "Đấu tốc độ": create a race, the race lobby (also opened from ?race=<code>) and the live results table.
// Presentation + thin API glue only. Race runs are never ranked; the server owns every score.
import * as api from './api.js';
import { TOPICS } from './pieces.js';
import { el, toast } from './ui.js';
import { icon } from './icons.js';
import { keycap } from './keycap.js';
import { showStrip, setMode, setStreak } from './strip.js';
import { ensureNickname, renewNickname, getNickname, getDeviceId } from './identity.js';
import { rankMark, fmtTime, fmtScore, LEVEL_NAME } from './rank-ui.js';
import { setUrl } from './rooms.js';

const $ = (id) => document.getElementById(id);
const POLL_MS = 3000;

let nav = { show: () => {}, home: () => {}, level: () => 'beginner', playRun: () => {} };
let lobbyToken = 0;
let lobbyWatch = null;

export function initRace(n) {
  nav = { ...nav, ...n };
  $('btn-race-new').addEventListener('click', () => openRaceNew());
  $('rc-home').addEventListener('click', () => nav.home());
  $('rc-link').addEventListener('focus', (e) => e.target.select());
  $('rc-copy').addEventListener('click', () => copyLink($('rc-link').value, $('rc-link')));
}

export const raceUrl = (code) => `${location.origin}${location.pathname.replace(/index\.html$/, '')}?race=${encodeURIComponent(code)}`;

export async function copyText(text, input) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    if (input) {
      input.focus();
      input.select();
    }
    try {
      return document.execCommand('copy');
    } catch {
      return false;
    }
  }
}

export async function copyLink(url, input = null) {
  toast((await copyText(url, input)) ? 'Đã sao chép liên kết.' : 'Hãy nhấn Ctrl+C để sao chép liên kết đang được chọn.');
}

function submitKey(label) {
  const k = keycap({ tag: 'button', topic: 'neutral', legend: label, legendClass: 'kb-label', variant: 'btn', enter: true });
  k.type = 'submit';
  return k;
}
function showErr(id, msg) {
  const p = $(id);
  p.replaceChildren(...(msg ? [icon('alert', { size: 16 }), el('span', { text: msg })] : []));
  p.hidden = !msg;
}
const raceError = (e) => ({
  404: 'Không tìm thấy trận này. Hãy kiểm tra lại mã.',
  410: 'Trận đã hết hạn hoặc đã đủ người chơi.',
  429: 'Bạn tạo trận quá nhanh. Hãy đợi một lát rồi thử lại.',
}[e.status] || e.message);

// ---- results table ---------------------------------------------------------------------------------------
/** The row that belongs to the player. The server marks it (`you: true`, from the device id); the
 *  nickname match is only a fallback for responses without the flag (mock mode, older servers). */
function mineIndex(results, mine) {
  const flagged = results.findIndex((r) => r.you === true);
  if (flagged >= 0 || results.some((r) => r.you === false)) return flagged;
  if (!mine?.nickname) return -1;
  const same = results.map((r, i) => [r, i]).filter(([r]) => r.nickname === mine.nickname);
  if (!same.length) return -1;
  if (mine.score != null) return (same.find(([r]) => r.score === mine.score) || [null, -1])[1];
  return same.length === 1 ? same[0][1] : -1;
}

export function resultsTable(results, mine = null) {
  if (!results?.length) return el('p', { class: 'tp-none rt-empty', text: 'Chưa có ai về đích. Hãy là người đầu tiên.' });
  const me = mineIndex(results, mine);
  const head = el('tr', {},
    el('th', { scope: 'col', class: 'rt-rank', text: '#' }),
    el('th', { scope: 'col', class: 'rt-name', text: 'Tên' }),
    el('th', { scope: 'col', class: 'rt-num', text: 'Điểm' }),
    el('th', { scope: 'col', class: 'rt-num rt-wide', text: 'Lock' }),
    el('th', { scope: 'col', class: 'rt-num rt-wide', text: 'Lỗi' }),
    el('th', { scope: 'col', class: 'rt-num rt-wide', text: 'Thời gian' }));
  const rows = results.map((r, i) => el('tr', { class: i === me ? 'is-me' : '', 'aria-current': i === me ? 'true' : false },
    el('td', { class: 'rt-rank' }, rankMark(r.rank || i + 1)),
    el('td', { class: 'rt-name' },
      el('span', { class: 'rt-nick', text: r.nickname }),
      i === me ? el('span', { class: 'lb-you', text: 'bạn' }) : null,
      el('span', { class: 'rt-meta', text: `${r.locks} hàng · ${r.mistakes} lỗi · ${fmtTime(r.duration_s)}` })),
    el('td', { class: 'rt-num rt-score', text: fmtScore(r.score) }),
    el('td', { class: 'rt-num rt-wide', text: String(r.locks) }),
    el('td', { class: 'rt-num rt-wide', text: String(r.mistakes) }),
    el('td', { class: 'rt-num rt-wide', text: fmtTime(r.duration_s) })));
  return el('div', { class: 'rt-scroll' },
    el('table', { class: 'rt' }, el('caption', { class: 'sr-only', text: 'Kết quả trận, xếp theo điểm rồi đến thời gian' }), el('thead', {}, head), el('tbody', {}, ...rows)));
}

/** Shown instead of a rank when the finished run was not the device's first in the race (the server says so with `practice: true`). */
export function practiceNote() {
  return el('p', { class: 'rk-note rt-practice', role: 'status', text: 'Lượt chơi lại: chỉ lượt đầu tiên được tính trên bảng.' });
}

export function syncNode() {
  return el('span', { class: 'tp-sync', role: 'status' }, el('i', { class: 'led on', style: { '--c': 'var(--ok)' } }), el('span', { text: 'cập nhật mỗi 3 giây' }));
}
function setSync(node, state) {
  if (!node) return;
  const bad = state === 'error' || state === 'gone';
  node.firstChild.style.setProperty('--c', bad ? 'var(--crash)' : 'var(--ok)');
  node.classList.toggle('is-bad', bad);
  node.lastChild.textContent = state === 'gone' ? 'trận không còn tồn tại' : bad ? 'mất kết nối, đang thử lại' : 'cập nhật mỗi 3 giây';
}

/**
 * Renders results into `host` and refreshes them every 3 s while `active()` is true.
 * opts: { code, host, status?, mine: () => ({nickname, score?}) | null, active: () => boolean, initial?: raceJson, onData?: fn }
 */
export function watchRace({ code, host, status = null, mine = () => null, active, initial = null, onData = null }) {
  let timer = null;
  let stopped = false;
  let data = initial;
  let key = '';
  let practice = !!initial?.practice; // sticky: only the finish response carries it, the 3 s polls do not
  const api_ = {
    stop() {
      stopped = true;
      clearTimeout(timer);
    },
    push(d) {
      data = d;
      if (d?.practice === true) practice = true;
      api_.repaint();
    },
    repaint() {
      if (!data || stopped) return;
      const k = JSON.stringify([data.results, mine(), practice]);
      if (k === key) return;
      key = k;
      host.replaceChildren(...(practice ? [practiceNote()] : []), resultsTable(data.results, mine()));
    },
    get data() {
      return data;
    },
  };
  const next = () => {
    if (!stopped) timer = setTimeout(tick, POLL_MS);
  };
  async function tick() {
    if (stopped) return;
    if (!active()) return api_.stop();
    if (document.hidden) return next();
    try {
      const d = await api.getRace(code);
      if (stopped) return;
      data = d;
      api_.repaint();
      setSync(status, 'ok');
      if (onData) onData(d);
    } catch (e) {
      if (stopped) return;
      if (e.status === 404 || e.status === 410) {
        setSync(status, 'gone');
        return api_.stop();
      }
      setSync(status, 'error');
    }
    next();
  }
  if (data) api_.repaint();
  timer = setTimeout(tick, data ? POLL_MS : 0);
  return api_;
}

// ---- create ------------------------------------------------------------------------------------------------
export function openRaceNew() {
  stopLobby();
  nav.show('screen-race-new');
  showStrip(true, { back: () => nav.home(), backLabel: 'Về màn hình chính' });
  setMode('ĐẤU TỐC ĐỘ');
  setStreak(null);
  const r = document.querySelector(`input[name=race-level][value=${nav.level()}]`);
  if (r) r.checked = true;
  showErr('race-new-err', '');
  const act = $('race-new-act');
  if (!act.firstChild) act.append(submitKey('Tạo trận'));
  const key = act.firstChild;
  const label = (busy) => {
    key.disabled = busy;
    key.querySelector('.kb-label').textContent = busy ? 'Đang tạo…' : 'Tạo trận';
  };
  label(false);
  const form = $('race-new-form');
  if (!form._wired) {
    form._wired = true;
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      if (key.disabled) return;
      showErr('race-new-err', '');
      label(true);
      try {
        const cardOpts = { title: 'Tên của bạn trong trận', confirmLabel: 'Dùng tên này' };
        let nickname = await ensureNickname(cardOpts);
        if (!nickname) return;
        const level = document.querySelector('input[name=race-level]:checked')?.value || 'beginner';
        let res;
        try {
          res = await api.createRace({ level, nickname, device_id: getDeviceId() });
        } catch (e2) {
          if (e2.status !== 422) throw e2;
          nickname = await renewNickname(cardOpts); // an old free-text name was stored: new name card, retry once
          if (!nickname) return;
          res = await api.createRace({ level, nickname, device_id: getDeviceId() });
        }
        setUrl({ race: res.code });
        openRace(res.code, { created: true });
      } catch (err) {
        showErr('race-new-err', 'Không tạo được trận: ' + raceError(err));
      } finally {
        label(false);
      }
    });
  }
  $('race-new-title').focus({ preventScroll: true });
}

// ---- lobby -------------------------------------------------------------------------------------------------
function stopLobby() {
  lobbyToken++;
  if (lobbyWatch) lobbyWatch.stop();
  lobbyWatch = null;
}

/** opts.created: the player just made this race (primary button says "Bắt đầu chơi" instead of "Vào đấu"). */
export async function openRace(code, { created = false } = {}) {
  stopLobby();
  const mine = lobbyToken;
  code = String(code || '').toUpperCase();
  nav.show('screen-race');
  showStrip(true, { back: () => nav.home(), backLabel: 'Về màn hình chính' });
  setMode('ĐẤU TỐC ĐỘ · ' + code);
  setStreak(null);

  $('rc-code').setAttribute('aria-label', 'Mã trận ' + code.split('').join(' '));
  $('rc-code').replaceChildren(...[...code].map((ch, i) => {
    const k = keycap({ topic: TOPICS[i % 4], legend: ch, legendClass: 'legend legend-c' });
    k.setAttribute('aria-hidden', 'true');
    return k;
  }));
  $('rc-link').value = raceUrl(code);
  $('rc-title').textContent = created ? 'Trận đã sẵn sàng' : 'Đấu tốc độ';
  $('rc-sub').textContent = 'Đang tìm trận…';
  $('rc-level').textContent = '';
  $('rc-mock').hidden = !api.isMock;
  $('rc-results').replaceChildren(el('p', { class: 'tp-none', text: 'Đang tải…' }));
  showErr('rc-err', '');
  const act = $('rc-act');
  act.replaceChildren();
  const status = $('rc-sync');
  status.replaceChildren(syncNode());

  let data;
  try {
    data = await api.getRace(code);
  } catch (e) {
    if (mine !== lobbyToken) return;
    $('rc-sub').textContent = '';
    $('rc-results').replaceChildren();
    showErr('rc-err', raceError(e));
    $('rc-title').focus({ preventScroll: true });
    return;
  }
  if (mine !== lobbyToken) return;

  $('rc-level').textContent = LEVEL_NAME[data.level] || data.level;
  const playing = data.playing > 0 ? ` · ${data.playing} người đang chơi` : '';
  $('rc-sub').textContent = `Tạo bởi ${data.created_by} · Code Rescue · cùng một đề cho mọi người${playing}`;
  const start = keycap({ tag: 'button', topic: 'neutral', legend: created ? 'Bắt đầu chơi' : 'Vào đấu', legendClass: 'kb-label', variant: 'btn', enter: true });
  start.type = 'button';
  start.addEventListener('click', () => nav.playRun('race', data.level, code));
  act.replaceChildren(start);
  $('rc-title').focus({ preventScroll: true });

  lobbyWatch = watchRace({
    code,
    host: $('rc-results'),
    status: status.firstChild,
    initial: data,
    mine: () => ({ nickname: getNickname() }),
    active: () => mine === lobbyToken && !$('screen-race').hidden,
    onData: (d) => {
      if (mine !== lobbyToken) return;
      $('rc-sub').textContent = `Tạo bởi ${d.created_by} · Code Rescue · cùng một đề cho mọi người${d.playing > 0 ? ` · ${d.playing} người đang chơi` : ''}`;
    },
  });
}
