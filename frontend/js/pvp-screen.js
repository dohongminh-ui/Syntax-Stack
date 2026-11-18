// "Đối kháng 1v1": the entry screen (quick match / private duel / bot), the search and waiting states, and the
// glue between the socket (pvp.js) and the live match (pvp-match.js). Tickets come from HTTP; the match runs on a WebSocket.
import * as api from './api.js';
import { PvpClient, getRating, storeTicket, loadTicket, clearTicket } from './pvp.js';
import { PvpMatch } from './pvp-match.js';
import { ensureNickname, renewNickname, askNickname, getNickname, getDeviceId } from './identity.js';
import { el, toast } from './ui.js';
import { icon } from './icons.js';
import { keycap } from './keycap.js';
import { showStrip, setMode, setStreak } from './strip.js';
import { copyLink } from './race.js';
import { setUrl } from './rooms.js';
import { TOPICS } from './pieces.js';
import { LEVEL_NAME, fmtTime } from './rank-ui.js';
import { LADDER, misakiTitle, misakiAvatar } from './misaki.js';

const $ = (id) => document.getElementById(id);
const BOT_OFFER_S = 20;
const NAME_CARD = { title: 'Tên của bạn trong trận đối kháng', confirmLabel: 'Dùng tên này' };

let nav = { show: () => {}, home: () => {}, level: () => 'beginner', getBoard: () => null };
let S = null; // the live session, see newSession()
let flow = 0; // bumps on every start / leave so a late HTTP answer cannot revive a cancelled flow
let creating = false;
let ladder = { unlocked: 1, wins: {}, games: {} }; // GET /api/pvp/misaki for this device
let pickedMisaki = 1;

function newSession(kind, level) {
  return { kind, level, misaki: null, training: false, ticket: null, code: null, client: null, match: null, nickname: '', timer: null, t0: 0, phase: 'menu' };
}

export function initPvp(n) {
  nav = { ...nav, ...n };
  $('btn-pvp').addEventListener('click', () => openPvp());
  $('pv-home').addEventListener('click', () => nav.home());
  $('pv-mock').hidden = !api.isMock;
  $('pv-rename').addEventListener('click', async () => {
    const name = await askNickname({ title: getNickname() ? 'Đổi tên' : 'Chọn tên', text: 'Tên được tạo ngẫu nhiên. Đối thủ sẽ thấy tên này.', confirmLabel: 'Dùng tên này' });
    if (name) {
      paintIdentity();
      toast('Đã lưu tên.');
    }
    $('pv-rename').focus({ preventScroll: true });
  });
  $('pv-code-in').addEventListener('input', (e) => {
    e.target.value = e.target.value.toUpperCase().replace(/[^A-Z0-9]/g, '');
    showErr('');
  });
  $('pv-join-form').addEventListener('submit', (e) => {
    e.preventDefault();
    const code = $('pv-code-in').value.trim().toUpperCase();
    if (code.length !== 5) {
      showErr('Mã trận gồm 5 ký tự.');
      $('pv-code-in').focus();
      return;
    }
    begin('join', { code });
  });
  $('pv-copy').addEventListener('click', () => copyLink($('pv-link').value, $('pv-link')));
  $('pv-link').addEventListener('focus', (e) => e.target.select());
  buildOptions();
  $('pv-mk-av').replaceChildren(misakiAvatar());
  $('pv-train').addEventListener('change', paintMisakiGo);
  $('pv-mk-go').addEventListener('click', () => begin('bot', { misaki: pickedMisaki, training: $('pv-train').checked }));
  paintLadder();
}

// ---- entry screen ------------------------------------------------------------------------------------------------
function buildOptions() {
  const items = [
    ['Tìm trận', 'Ghép nhanh với một người chơi cùng cấp độ', 'search', () => begin('quick')],
    ['Đấu với bạn', 'Tạo mã trận, gửi cho bạn bè', 'layers', () => begin('private')],
  ];
  $('pv-options').replaceChildren(...items.map(([label, desc, ic, go]) => {
    const b = keycap({
      tag: 'button', topic: 'neutral', legendClass: 'practice-body', cls: 'practice-key',
      legend: el('span', { class: 'practice-in' }, icon(ic, { size: 22, cls: 'practice-ico' }),
        el('span', { class: 'practice-text' }, el('span', { class: 'practice-label', text: label }), el('span', { class: 'practice-desc', text: desc })),
        icon('chevron-right', { size: 20, cls: 'practice-go' })),
    });
    b.type = 'button';
    b.addEventListener('click', go);
    return el('li', { class: 'practice-item' }, b);
  }));
}

/** The four Misaki keycaps. Locked levels are dimmed, carry a lock icon and say how to open them. */
function paintLadder() {
  const unlocked = Math.min(4, Math.max(1, Number(ladder.unlocked) || 1));
  if (pickedMisaki > unlocked || pickedMisaki < 1) pickedMisaki = unlocked;
  $('pv-mk-ladder').replaceChildren(...LADDER.map(({ level, name }) => {
    const locked = level > unlocked;
    const input = el('input', { class: 'sr-only', type: 'radio', name: 'pv-mk', value: String(level) });
    input.checked = level === pickedMisaki;
    input.disabled = locked;
    input.addEventListener('change', () => {
      pickedMisaki = level;
      paintMisakiGo();
    });
    const label = el('span', { class: 'kb-label pv-lk-in' },
      locked ? icon('lock', { size: 16, cls: 'pv-lk-ico' }) : null,
      el('span', { class: 'pv-lk-name', text: name }),
      locked ? el('span', { class: 'pv-lk-note', text: 'Thắng cấp trước để mở' }) : null);
    return el('label', { class: 'key keyopt pv-lk' + (locked ? ' is-off' : ''), title: locked ? 'Thắng cấp trước để mở' : `Misaki · ${name}` },
      input, el('span', { class: 'cap-top' }, label));
  }));
  paintMisakiGo();
}

function paintMisakiGo() {
  const train = $('pv-train').checked;
  const l = $('pv-mk-go').querySelector('.kb-label');
  l.textContent = train ? `Luyện tập với ${misakiTitle(pickedMisaki)}` : `Đấu với ${misakiTitle(pickedMisaki)}`;
}

async function loadLadder() {
  try {
    const r = await api.pvpMisaki(getDeviceId());
    if (r && typeof r === 'object') ladder = { unlocked: Number(r.unlocked) || 1, wins: r.wins || {}, games: r.games || {} };
  } catch {
    /* offline or an old server: only level 1 is offered */
  }
  if (S && S.phase === 'menu') paintLadder();
}

function paintIdentity() {
  const n = getNickname();
  $('pv-name').textContent = n || 'Chưa có tên (sẽ được tạo khi bạn bắt đầu)';
  $('pv-name').classList.toggle('is-none', !n);
  $('pv-rename').textContent = n ? 'Đổi tên' : 'Chọn tên';
  const r = getRating();
  const chip = $('pv-rating');
  chip.hidden = r == null;
  if (r != null) {
    chip.textContent = `${r}`;
    chip.title = 'Xếp hạng đối kháng';
    chip.setAttribute('aria-label', `Xếp hạng đối kháng ${r}`);
  }
}

function showErr(msg) {
  const p = $('pv-err');
  p.replaceChildren(...(msg ? [icon('alert', { size: 16 }), el('span', { text: msg })] : []));
  p.hidden = !msg;
}

function pane(name) {
  for (const id of ['pv-menu', 'pv-search', 'pv-wait']) $(id).hidden = id !== 'pv-' + name;
  $('pv-level').hidden = true;
  if (S) S.phase = name;
}

function selectedLevel() {
  return document.querySelector('input[name=pv-level]:checked')?.value || 'beginner';
}

export function openPvp() {
  stopSession();
  nav.show('screen-pvp');
  S = newSession('menu', selectedLevel());
  showStrip(true, { back: backFromPvp, backLabel: 'Quay lại' });
  setMode('ĐỐI KHÁNG');
  setStreak(null);
  const r = document.querySelector(`input[name=pv-level][value=${nav.level()}]`);
  if (r) r.checked = true;
  $('pv-title').textContent = 'Đối kháng 1v1';
  showErr('');
  paintIdentity();
  paintLadder();
  loadLadder();
  pane('menu');
  $('pv-title').focus({ preventScroll: true });
}

/** Presenter shortcut: prepare ordinary training controls without starting a match. */
export function openMisakiTraining() {
  pickedMisaki = 1;
  openPvp();
  $('pv-train').checked = true;
  paintMisakiGo();
}

function backFromPvp() {
  if (S && (S.phase === 'search' || S.phase === 'wait')) return cancel();
  nav.home();
}

/** /?duel=<code> on boot: join that duel straight away. */
export function openDuel(code) {
  openPvp();
  setUrl(); // keep ?mock=1 but drop ?duel so a reload does not try to join twice
  $('pv-code-in').value = String(code || '').toUpperCase().replace(/[^A-Z0-9]/g, '').slice(0, 5);
  if ($('pv-code-in').value.length === 5) begin('join', { code: $('pv-code-in').value });
  else showErr('Mã trận gồm 5 ký tự.');
}

/** Called from goHome: drop the socket, the queue ticket and any match UI. */
export function leaveAll() {
  stopSession();
  flow++;
}

function stopSession() {
  const s = S;
  S = null;
  if (!s) return;
  clearInterval(s.timer);
  if (s.match) s.match.teardown();
  if (s.client) s.client.close();
  if (s.kind === 'quick' && s.ticket && !s.matched) api.pvpLeaveQueue(s.ticket).catch(() => {});
  clearTicket();
}

// ---- starting a flow ---------------------------------------------------------------------------------------------
const START_ERR = {
  403: 'Cấp này của Misaki chưa mở. Hãy thắng cấp trước.',
  429: 'Bạn thao tác hơi nhanh. Đợi một lát rồi thử lại.',
};
const JOIN_ERR = {
  404: 'Không tìm thấy trận này. Hãy kiểm tra lại mã.',
  409: 'Trận này đã đủ hai người chơi.',
  410: 'Mã này đã hết hạn (10 phút không có người vào). Hãy xin bạn bè một mã mới.',
  429: 'Bạn thao tác hơi nhanh. Đợi một lát rồi thử lại.',
};

/** Runs `call(nickname)`; a 422 (old free-text name) shows the name card again and retries once. */
async function withName(call) {
  let nickname = await ensureNickname(NAME_CARD);
  if (!nickname) return null;
  try {
    return { nickname, res: await call(nickname) };
  } catch (e) {
    if (e.status !== 422) throw e;
    nickname = await renewNickname(NAME_CARD);
    if (!nickname) return null;
    return { nickname, res: await call(nickname) };
  }
}

async function begin(kind, { code = null, misaki = null, training = false } = {}) {
  if (creating) return;
  creating = true;
  showErr('');
  const mine = ++flow;
  const level = kind === 'join' ? selectedLevel() : selectedLevel();
  try {
    const device_id = getDeviceId();
    const got = await withName((nickname) => {
      if (kind === 'quick') return api.pvpQueue({ level, nickname, device_id });
      if (kind === 'private') return api.pvpPrivate({ level, nickname, device_id });
      if (kind === 'bot') return api.pvpBot({ level, nickname, device_id, misaki: misaki || 1, training: !!training });
      return api.pvpJoinPrivate(code, { nickname, device_id });
    });
    if (!got || mine !== flow) return;
    const { nickname, res } = got;
    if (!res?.ticket) throw new Error('Máy chủ không trả về vé vào trận.');
    stopSession();
    S = newSession(kind, level);
    if (kind === 'bot') {
      S.misaki = misaki || 1;
      S.training = !!training;
    }
    S.nickname = nickname;
    S.ticket = res.ticket;
    S.code = res.code || code;
    S.url = res.url || null;
    S.flow = mine;
    showStrip(true, { back: backFromPvp, backLabel: 'Quay lại' });
    paintWaiting();
    connect();
  } catch (e) {
    if (mine !== flow) return;
    const map = kind === 'join' ? JOIN_ERR : START_ERR;
    showErr((kind === 'join' ? 'Không vào được trận: ' : 'Không bắt đầu được: ') + (map[e.status] || e.message));
    pane('menu');
    if (e.status === 403) loadLadder();
  } finally {
    creating = false;
  }
}

function paintWaiting() {
  const s = S;
  $('pv-level').hidden = false;
  $('pv-level').textContent = s.kind === 'join' ? 'Đang vào trận' : s.kind === 'bot' && s.misaki ? misakiTitle(s.misaki) + (s.training ? ' · luyện tập' : '') : LEVEL_NAME[s.level] || s.level;
  if (s.resuming) {
    pane('search');
    $('pv-level').hidden = true;
    $('pv-title').textContent = 'Đang vào lại trận';
    $('pv-search-t').textContent = 'Đang vào lại trận của bạn…';
    $('pv-search-note').textContent = 'Trang vừa được tải lại. Trận vẫn được giữ trong 20 giây.';
    $('pv-time').textContent = '';
    $('pv-search-act').replaceChildren(el('button', { class: 'btn', type: 'button', text: 'Bỏ trận này', onclick: () => cancel() }));
  } else if (s.kind === 'quick') {
    pane('search');
    $('pv-level').hidden = false;
    $('pv-title').textContent = 'Đang tìm đối thủ';
    $('pv-search-t').textContent = 'Đang tìm đối thủ…';
    $('pv-search-note').textContent = `Hai người cùng cấp độ ${LEVEL_NAME[s.level] || s.level} được ghép với nhau.`;
    $('pv-time').textContent = '0:00';
    const cancelBtn = el('button', { class: 'btn', type: 'button', text: 'Hủy tìm trận', onclick: () => cancel() });
    $('pv-search-act').replaceChildren(cancelBtn);
    s.t0 = Date.now();
    s.botOffered = false;
    s.timer = setInterval(() => {
      const t = Math.floor((Date.now() - s.t0) / 1000);
      $('pv-time').textContent = fmtTime(t);
      if (t >= BOT_OFFER_S && !s.botOffered && S === s && !s.matched) offerBot();
    }, 500);
    cancelBtn.focus({ preventScroll: true });
  } else if (s.kind === 'private') {
    pane('wait');
    $('pv-level').hidden = false;
    $('pv-title').textContent = 'Trận đã sẵn sàng';
    $('pv-wait-t').textContent = 'Đang chờ bạn bè vào…';
    $('pv-code').setAttribute('aria-label', 'Mã trận ' + s.code.split('').join(' '));
    $('pv-code').replaceChildren(...[...s.code].map((ch, i) => {
      const k = keycap({ topic: TOPICS[i % 4], legend: ch, legendClass: 'legend legend-c' });
      k.setAttribute('aria-hidden', 'true');
      return k;
    }));
    $('pv-link').value = s.url || duelUrl(s.code);
    $('pv-wait-act').replaceChildren(el('button', { class: 'btn', type: 'button', text: 'Hủy trận', onclick: () => cancel() }));
    $('pv-title').focus({ preventScroll: true });
  } else {
    // join / bot: nothing to wait for but the socket
    pane('search');
    $('pv-level').hidden = false;
    $('pv-title').textContent = s.kind === 'bot' ? 'Đang vào trận với Misaki' : 'Đang vào trận';
    $('pv-search-t').textContent = s.kind === 'bot' ? 'Misaki đang vào bàn…' : 'Đang vào trận…';
    $('pv-search-note').textContent = '';
    $('pv-time').textContent = '';
    $('pv-search-act').replaceChildren(el('button', { class: 'btn', type: 'button', text: 'Hủy', onclick: () => cancel() }));
  }
}

const duelUrl = (code) => `${location.origin}${location.pathname.replace(/index\.html$/, '')}?${api.isMock ? 'mock=1&' : ''}duel=${encodeURIComponent(code)}`;

function offerBot() {
  const s = S;
  s.botOffered = true;
  $('pv-search-t').textContent = 'Chưa thấy ai cùng cấp độ.';
  $('pv-search-note').textContent = 'Bạn có thể đấu với Misaki ngay (không tính xếp hạng), hoặc chờ thêm một chút.';
  const bot = keycap({ tag: 'button', topic: 'neutral', legend: 'Đấu với Misaki', legendClass: 'kb-label', variant: 'btn', enter: true });
  bot.type = 'button';
  bot.addEventListener('click', () => switchToBot());
  $('pv-search-act').prepend(bot);
}

async function switchToBot() {
  const level = S?.level || selectedLevel();
  cancel(true);
  const r = document.querySelector(`input[name=pv-level][value=${level}]`);
  if (r) r.checked = true;
  begin('bot', { misaki: pickedMisaki, training: false });
}

function cancel(quiet = false) {
  stopSession();
  flow++;
  creating = false;
  if (quiet) return;
  openPvp();
}

// ---- socket -> screens -------------------------------------------------------------------------------------------
function connect() {
  const s = S;
  const client = new PvpClient({
    ticket: s.ticket,
    onMessage: (msg) => {
      if (S !== s) return;
      route(msg);
    },
    onStatus: (status, info) => {
      if (S !== s) return;
      if (s.match) return s.match.onConnection(status, info);
      if (status === 'reconnecting') toast('Đang kết nối lại…', 1600);
      if (status === 'failed') {
        const msg = s.resuming ? 'Không vào lại được trận (có thể đã kết thúc).' : s.kind === 'join' ? 'Không vào được trận. Mã có thể đã hết hạn hoặc đã đủ người.' : 'Mất kết nối với máy chủ. Hãy thử lại.';
        stopSession();
        flow++;
        openPvp();
        showErr(msg);
      }
    },
  });
  s.client = client;
  client.connect();
}

function route(msg) {
  const s = S;
  if (s.match && s.match.ended && msg.t === 'start' && s.match.o.rematch) return startRematch(msg);
  if (s.match) return s.match.handle(msg);
  if (msg.t === 'lobby') {
    const opp = msg.opponent;
    if (opp && (opp.nickname || opp.bot)) return startMatch(msg);
    if (msg.you && typeof msg.you === 'object' && msg.you.rating != null) paintRatingHint(msg.you.rating);
    return;
  }
  if (msg.t === 'start' || msg.t === 'state') {
    // a reconnect landed straight in a running match
    startMatch({ t: 'lobby', opponent: {}, level: msg.level || s.level });
    return s.match.handle(msg);
  }
  if (msg.t === 'end') {
    stopSession();
    flow++;
    openPvp();
    showErr(msg.reason === 'server_restart' ? 'Máy chủ đang được cập nhật. Hãy thử lại sau ít phút.' : 'Trận đã kết thúc trước khi bắt đầu.');
  }
}

function paintRatingHint(r) {
  const chip = $('pv-rating');
  chip.hidden = false;
  chip.textContent = String(r);
}

function startMatch(lobby, { again = null } = {}) {
  const s = S;
  clearInterval(s.timer);
  s.matched = true;
  const you = again ? again.you : typeof lobby.you === 'string' ? { nickname: lobby.you } : lobby.you || {};
  const board = nav.getBoard();
  storeTicket({ ticket: s.ticket, kind: s.kind, level: lobby.level || s.level || 'beginner', nickname: s.nickname, misaki: s.misaki, training: s.training });
  const resumed = !!s.resuming;
  s.resuming = false;
  s.match = new PvpMatch({
    resumed,
    rematch: s.kind === 'private' || s.kind === 'join',
    board,
    client: s.client,
    show: nav.show,
    you: { nickname: s.nickname, ...you },
    opponent: withMisaki(lobby.opponent || {}, s),
    level: lobby.level || s.level || 'beginner',
    onRematch: () => rematch(),
    onMisaki: (opts) => playMisaki(opts),
    onHome: () => nav.home(),
    rematchNote: () => (s.kind === 'private' ? 'Đấu lại với bạn bè: một mã trận mới sẽ được tạo. Hãy gửi mã mới cho họ.' : ''),
  });
  if (!again) s.client.send({ t: 'ready' });
  s.match.handle(lobby);
}

/** A reload / re-sent lobby may lack the Misaki fields: fill them from what this session asked for. */
function withMisaki(opp, s) {
  if (s.kind !== 'bot' || !s.misaki || opp.misaki) return opp;
  return { ...opp, nickname: opp.nickname || 'Misaki', bot: true, misaki: s.misaki, title: misakiTitle(s.misaki), training: s.training };
}

/** From the end screen: another match against Misaki ({ misaki, training }). */
function playMisaki({ misaki, training }) {
  stopSession();
  flow++;
  creating = false;
  openPvp();
  pickedMisaki = misaki;
  $('pv-train').checked = !!training;
  paintLadder();
  begin('bot', { misaki, training: !!training });
}

/** A fresh `start` on the same socket after both players pressed "Đấu lại": a new match against the same opponent. */
function startRematch(msg) {
  const s = S;
  const old = s.match;
  const prev = { you: old.you, opponent: old.opponent, level: old.level };
  old.teardown();
  s.client.resume();
  startMatch({ t: 'lobby', opponent: prev.opponent, level: msg.level || prev.level }, { again: { you: prev.you } });
  s.match.handle(msg);
}

/** Boot: a live match ticket in sessionStorage means this page was reloaded mid-match. Reconnect with it. */
export function resumeIfAny() {
  const t = loadTicket();
  if (!t) return false;
  stopSession();
  nav.show('screen-pvp');
  S = newSession(t.kind || 'quick', t.level || 'beginner');
  S.ticket = t.ticket;
  S.nickname = t.nickname || getNickname();
  S.misaki = t.misaki || null;
  S.training = !!t.training;
  S.resuming = true;
  showStrip(true, { back: backFromPvp, backLabel: 'Quay lại' });
  setMode('ĐỐI KHÁNG');
  setStreak(null);
  showErr('');
  paintWaiting();
  connect();
  return true;
}

function rematch() {
  const s = S;
  const kind = s?.kind === 'join' ? 'private' : s?.kind || 'quick';
  const level = s?.match?.level || s?.level || selectedLevel();
  stopSession();
  flow++;
  creating = false;
  openPvp();
  const r = document.querySelector(`input[name=pv-level][value=${level}]`);
  if (r) r.checked = true;
  if (kind === 'bot') return begin('bot', { misaki: s?.misaki || pickedMisaki, training: !!s?.training });
  begin(kind);
}
