// Ranked / race run lifecycle: create the run on the server, hand its seed to the game, send the move log at the end
// and paint the verified result. The score shown as "verified" always comes from the server reply.
import * as api from './api.js';
import * as RunLog from './runlog.js';
import { ensureNickname, renewNickname, getDeviceId } from './identity.js';
import { el, confirmDialog, rollNumber } from './ui.js';
import { icon } from './icons.js';
import { fmtTime } from './rank-ui.js';
import * as Race from './race.js';

const $ = (id) => document.getElementById(id);

let nav = { openBoard: () => {} };
let last = null; // { kind, level, race } of the run being played / just played (for "Chơi lại")
let fin = null; // { run, moves, clientScore, race: watcher, verified? }

export function initRanked(n) {
  nav = { ...nav, ...n };
}

// ---- before the game --------------------------------------------------------------------------------------
const CREATE_ERR = {
  404: 'Không tìm thấy trận này.',
  410: 'Trận đã hết hạn hoặc đã đủ người chơi.',
  429: 'Bạn đã bắt đầu quá nhiều ván trong một giờ. Hãy thử lại sau.',
};

/**
 * Asks for a nickname once, then creates the run. Resolves { run } | { unranked: true } | null (cancelled / failed).
 * run = { id, token, seed, level, kind, race }
 */
export async function beginRun({ kind, level, race = null }) {
  const cardOpts = {
    title: kind === 'race' ? 'Tên của bạn trong trận' : 'Tên của bạn trên bảng xếp hạng',
    confirmLabel: 'Dùng tên này',
  };
  let nickname = await ensureNickname(cardOpts);
  if (!nickname) return null;
  try {
    let r;
    try {
      r = await api.createRun({ kind, level, nickname, device_id: getDeviceId(), ...(race ? { race } : {}) });
    } catch (e) {
      if (e.status !== 422) throw e;
      // an old free-text name is stored: forget it, show the name card, retry once
      nickname = await renewNickname(cardOpts);
      if (!nickname) return null;
      r = await api.createRun({ kind, level, nickname, device_id: getDeviceId(), ...(race ? { race } : {}) });
    }
    return { run: { id: r.run_id, token: r.run_token, seed: r.seed >>> 0, level: r.level || level, kind: r.kind || kind, race: r.race || race, nickname } };
  } catch (e) {
    const detail = CREATE_ERR[e.status] || 'Không kết nối được máy chủ.';
    if (kind === 'race') {
      await confirmDialog({ title: 'Chưa vào được trận', text: detail, buttons: [{ label: 'Đã hiểu', value: 'ok', variant: 'primary' }] });
      return null;
    }
    const ch = await confirmDialog({
      title: 'Chưa tạo được ván xếp hạng',
      text: `${detail} Bạn vẫn có thể chơi một ván Rescue không xếp hạng.`,
      buttons: [{ label: 'Chơi không xếp hạng', value: 'unranked', variant: 'primary' }, { label: 'Để sau', value: 'no', variant: 'ghost' }],
    });
    return ch === 'unranked' ? { unranked: true } : null;
  }
}

/** Called by startGame for every game: a run object arms the move log and the API run fields, null clears them. */
export function attach(run) {
  stopFin();
  fin = null;
  RunLog.start(run);
  api.setRunContext(run);
  last = run ? { kind: run.kind, level: run.level, race: run.race } : null;
  clearPanels();
}

/** Back to the home screen: forget everything about the run. */
export function detach() {
  attach(null);
}

export const lastRun = () => last;
export const isRun = () => !!RunLog.current();

// ---- after the game ----------------------------------------------------------------------------------------
function stopFin() {
  if (fin?.race) fin.race.stop();
}

function clearPanels() {
  for (const id of ['end-ranked', 'end-race']) {
    const n = $(id);
    if (n) {
      n.hidden = true;
      n.replaceChildren();
    }
  }
  const lab = $('end-score-l');
  if (lab) lab.textContent = 'ĐIỂM';
  const again = $('btn-again')?.querySelector('.kb-label');
  if (again) again.textContent = 'Chơi lại';
}

/** End screen is already filled with the local stats; this adds the ranked / race parts. G = finished game state. */
export function afterEnd(G) {
  clearPanels();
  const run = RunLog.current();
  if (!run) return;
  api.setRunContext(null); // the game is over: later puzzle calls (rematch, practice) must not be recorded in the run
  fin = { run, moves: RunLog.moves(), clientScore: G.score | 0, race: null };
  if (run.kind === 'race') {
    $('btn-again').querySelector('.kb-label').textContent = 'Chơi lại cùng đề';
    mountRace(run.race, run.nickname);
  }
  paintPending();
  submit();
}

function paintStatus(...kids) {
  const p = $('end-ranked');
  p.hidden = false;
  p.replaceChildren(...kids);
}

function paintPending() {
  $('end-score-l').textContent = 'ĐIỂM (CHƯA XÁC MINH)';
  paintStatus(el('p', { class: 'rk-status', role: 'status' }, el('i', { class: 'led on rk-pulse', style: { '--c': 'var(--warn)' } }), 'Đang xác minh ván chơi trên máy chủ…'));
}

function paintError(e, retry) {
  $('end-score-l').textContent = 'ĐIỂM (CHƯA XÁC MINH)';
  const msg = {
    403: 'Mã ván chơi không hợp lệ nên không gửi được kết quả.',
    409: 'Ván này đã được gửi trước đó.',
    410: 'Ván này đã quá hạn nên không còn gửi được kết quả.',
  }[e.status];
  if (msg) {
    paintStatus(el('p', { class: 'rk-status is-bad', role: 'alert' }, icon('alert', { size: 16 }), msg));
    return;
  }
  const btn = el('button', { class: 'btn', type: 'button', text: 'Thử lại' });
  btn.addEventListener('click', retry);
  paintStatus(
    el('p', { class: 'rk-status is-bad', role: 'alert' }, icon('alert', { size: 16 }), 'Chưa gửi được kết quả: ' + e.message),
    el('p', { class: 'rk-note', text: 'Ván chơi của bạn được giữ lại cho đến khi gửi được.' }),
    el('div', { class: 'rk-actions' }, btn));
}

async function submit() {
  const mine = fin;
  const { run } = mine;
  paintPending();
  let res;
  try {
    res = await api.finishRun(run.id, { run_token: run.token, moves: mine.moves, client_score: mine.clientScore });
  } catch (e) {
    if (fin !== mine || $('screen-end').hidden) return;
    paintError(e, submit);
    return;
  }
  if (fin !== mine || $('screen-end').hidden) return;
  RunLog.clear(); // delivered: the log is no longer needed
  if (res.status === 'verified') paintVerified(res, mine);
  else paintRejected(mine);
}

function paintRejected(mine) {
  $('end-score-l').textContent = 'ĐIỂM';
  paintStatus(el('p', { class: 'rk-status', role: 'status' }, icon('alert', { size: 16 }), 'Không xác minh được ván này nên không tính hạng.'));
  if (mine.run.kind === 'race' && fin?.race) fin.race.repaint();
}

const RANK_LABEL = [['day', 'Hôm nay'], ['week', 'Tuần này'], ['all', 'Mọi lúc']];

function paintVerified(res, mine) {
  $('end-score-l').textContent = 'ĐIỂM ĐÃ XÁC MINH';
  rollNumber($('end-score'), res.score, 900);
  // the server's numbers replace the local receipt
  $('end-streak').textContent = res.best_streak;
  $('end-bugs').textContent = res.bugs_fixed;
  $('end-mist').textContent = res.mistakes;
  const kids = [];
  if (mine.run.kind === 'ranked') {
    const r = res.rank || {};
    const any = RANK_LABEL.some(([k]) => r[k]);
    kids.push(any
      ? el('ul', { class: 'rk-ranks', 'aria-label': 'Hạng của bạn' }, ...RANK_LABEL.map(([k, label]) =>
          el('li', { class: 'rk-chip' + (r[k] ? '' : ' is-none') }, el('span', { class: 'rk-chip-l', text: label }), el('b', { text: r[k] ? '#' + r[k] : '–' }))))
      : el('p', { class: 'rk-status', role: 'status' }, icon('trophy', { size: 16 }), 'Chưa vào bảng'));
  }
  kids.push(el('p', { class: 'rk-meta', text: `${res.locks} hàng đã gỡ · ${fmtTime(res.duration_s)}` }));
  if (mine.run.kind === 'ranked') {
    const btn = el('button', { class: 'btn', type: 'button' }, icon('trophy', { size: 16 }), 'Xem bảng xếp hạng');
    btn.addEventListener('click', () => nav.openBoard(mine.run.level));
    kids.push(el('div', { class: 'rk-actions' }, btn));
  }
  paintStatus(el('div', { class: 'rk-ok', role: 'status' }, ...kids));
  if (mine.run.kind === 'race') {
    mine.verified = { nickname: mine.run.nickname, score: res.score };
    if (res.race && fin?.race) fin.race.push(res.race);
    else if (fin?.race) fin.race.repaint();
  }
}

function mountRace(code, nickname) {
  const panel = $('end-race');
  panel.hidden = false;
  const host = el('div', { class: 'rt-host' });
  const sync = Race.syncNode();
  const invite = el('button', { class: 'btn', type: 'button', text: 'Mời thêm bạn' });
  invite.addEventListener('click', () => Race.copyLink(Race.raceUrl(code)));
  panel.replaceChildren(
    el('div', { class: 'rc-res-head' }, el('h2', { class: 'report-h', text: `Kết quả trận ${code}` }), sync),
    host,
    el('p', { class: 'rk-note', text: 'Không tính vào bảng xếp hạng. Mọi người chơi cùng một đề.' }),
    el('div', { class: 'rk-actions' }, invite));
  const mine = fin;
  fin.race = Race.watchRace({
    code,
    host,
    status: sync,
    mine: () => mine.verified || { nickname },
    active: () => fin === mine && !$('screen-end').hidden,
  });
}
