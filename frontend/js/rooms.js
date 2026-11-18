// Live classroom ("Lớp học trực tiếp"): teacher create + dashboard, student join, progress reporting.
// Pure presentation + thin API glue. The server owns all data; nothing here decides scores.
import * as api from './api.js';
import { TOPICS, TOPIC_NAMES, TOPIC_GLYPH, PUZZLE_TYPES, TYPE_NAMES, TYPE_SHORT } from './pieces.js';
import { el, anim, toast, confirmDialog, wait } from './ui.js';
import { icon } from './icons.js';
import { keycap } from './keycap.js';
import { showStrip, setMode, setStreak } from './strip.js';

const $ = (id) => document.getElementById(id);
const LEVEL_NAME = { beginner: 'Beginner', intermediate: 'Intermediate', advanced: 'Advanced' };
const ROOMS_KEY = 'syntaxstack.rooms';
const SESSION_KEY = 'syntaxstack.room';
const POLL_MS = 2000;
const STALE_S = 60;

let nav = { show: () => {}, home: () => {}, play: () => {}, level: () => 'beginner' };

export function initRooms(n) {
  nav = { ...nav, ...n };
  $('btn-room-new').addEventListener('click', () => openRoomNew());
  $('room-code-in').addEventListener('input', (e) => {
    e.target.value = e.target.value.toUpperCase().replace(/[^A-Z0-9]/g, '');
    $('room-code-err').hidden = true;
  });
  $('room-code-form').addEventListener('submit', (e) => {
    e.preventDefault();
    const code = $('room-code-in').value.trim().toUpperCase();
    if (code.length !== 5) {
      const p = $('room-code-err');
      p.textContent = 'Mã phòng gồm 5 ký tự.';
      p.hidden = false;
      $('room-code-in').focus();
      return;
    }
    setUrl({ room: code });
    openJoin(code);
  });
  $('btn-leave-room').addEventListener('click', () => nav.home());
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden && poll && !$('screen-room-teach').hidden) pollNow();
  });
  document.addEventListener('fullscreenchange', paintFs);
}

// ---- storage / url -----------------------------------------------------------------------------
function loadRooms() {
  try {
    const v = JSON.parse(localStorage.getItem(ROOMS_KEY));
    return v && typeof v === 'object' ? v : {};
  } catch {
    return {};
  }
}
function saveRooms(all) {
  try {
    localStorage.setItem(ROOMS_KEY, JSON.stringify(all));
  } catch {
    /* storage blocked */
  }
}
export function getStudent() {
  try {
    const v = JSON.parse(sessionStorage.getItem(SESSION_KEY));
    return v && v.code && v.player_token ? v : null;
  } catch {
    return null;
  }
}
function setStudent(v) {
  try {
    if (v) sessionStorage.setItem(SESSION_KEY, JSON.stringify(v));
    else sessionStorage.removeItem(SESSION_KEY);
  } catch {
    /* ignore */
  }
  api.setRoomContext(v);
}
/** Rewrites the address bar to `/?<params>` keeping ?mock=1. No navigation. */
export function setUrl(params = {}) {
  const q = new URLSearchParams();
  if (api.isMock) q.set('mock', '1');
  for (const [k, v] of Object.entries(params)) q.set(k, v);
  const s = q.toString();
  try {
    history.replaceState(null, '', location.pathname + (s ? '?' + s : ''));
  } catch {
    /* ignore */
  }
}

/** Called from goHome: drop any student room and stop teacher polling. */
export function leaveAll() {
  stopPoll();
  setStudent(null);
  resetProgress();
  if (document.fullscreenElement) document.exitFullscreen?.().catch(() => {});
  setUrl();
}

export function syncChip(screenId) {
  const chip = $('strip-room');
  const s = getStudent();
  const on = !!s && ['screen-game', 'screen-end'].includes(screenId);
  chip.hidden = !on;
  $('strip').classList.toggle('has-room', on);
  if (on) chip.textContent = `PHÒNG ${s.code} · ${s.nickname}`;
  $('strip').classList.toggle('strip-teach', screenId === 'screen-room-teach');
  const inRoom = !!s;
  $('btn-leave-room').hidden = !inRoom;
  $('btn-menu').hidden = inRoom;
}

// ---- shared bits -------------------------------------------------------------------------------
function submitKey(label) {
  const k = keycap({ tag: 'button', topic: 'neutral', legend: label, legendClass: 'kb-label', variant: 'btn', enter: true });
  k.type = 'submit';
  return k;
}
function setBusy(k, busy, label) {
  k.disabled = busy;
  k.querySelector('.kb-label').textContent = busy ? 'Đang xử lý…' : label;
}
function showErr(id, msg) {
  const p = $(id);
  p.replaceChildren(icon('alert', { size: 16 }), el('span', { text: msg }));
  p.hidden = !msg;
}
const joinHost = () => location.host + '/?room=';

// ---- teacher: create ---------------------------------------------------------------------------
export function openRoomNew() {
  nav.show('screen-room-new');
  showStrip(true, { back: () => nav.home(), backLabel: 'Về màn hình chính' });
  setMode('LỚP HỌC');
  setStreak(null);
  const lv = nav.level();
  const r = document.querySelector(`input[name=room-level][value=${lv}]`);
  if (r) r.checked = true;
  showErr('room-new-err', '');
  const rn = document.querySelector('input[name=room-names][value=random]');
  if (rn) rn.checked = true;
  paintNamesNote();
  const form = $('room-new-form');
  const act = $('room-new-act');
  if (!act.firstChild) act.append(submitKey('Mở phòng'));
  const key = act.firstChild;
  key.disabled = false;
  if (!form._wired) {
    form._wired = true;
    document.querySelectorAll('input[name=room-names]').forEach((i) => i.addEventListener('change', paintNamesNote));
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      if (key.disabled) return;
      setBusy(key, true, 'Mở phòng');
      showErr('room-new-err', '');
      try {
        const level = document.querySelector('input[name=room-level]:checked')?.value || 'beginner';
        const title = $('room-title-in').value.trim();
        const names = document.querySelector('input[name=room-names]:checked')?.value === 'free' ? 'free' : 'random';
        const res = await api.createRoom({ level, names, ...(title ? { title } : {}) });
        const all = loadRooms();
        all[res.code] = { teacher_key: res.teacher_key, created: Date.now() };
        saveRooms(all);
        setUrl({ teach: res.code });
        openTeach(res.code);
      } catch (err) {
        showErr('room-new-err', err.status === 429 ? 'Bạn mở phòng quá nhanh. Hãy đợi một lát rồi thử lại.' : 'Không mở được phòng: ' + err.message);
      } finally {
        setBusy(key, false, 'Mở phòng');
      }
    });
  }
  $('room-new-title').focus({ preventScroll: true });
}

function paintNamesNote() {
  const free = document.querySelector('input[name=room-names]:checked')?.value === 'free';
  $('room-names-note').textContent = free ? 'Có bộ lọc từ ngữ; giáo viên có thể ẩn người chơi' : 'Nên dùng khi chiếu lên màn hình lớn';
}

// ---- teacher: dashboard --------------------------------------------------------------------------
let poll = null; // { code, key, timer, token, fetching }
let teachView = null; // cached DOM refs + last rendered json per block
let pollToken = 0;

function stopPoll() {
  if (poll) clearTimeout(poll.timer);
  poll = null;
  pollToken++;
}

export function openTeach(code) {
  stopPoll();
  code = String(code || '').toUpperCase();
  let entry = loadRooms()[code];
  if (!entry && api.isMock) {
    // ?mock=1&teach=DEMO1: no real room was created on this machine, so grant the mock key.
    entry = { teacher_key: 'mock-key', created: Date.now() };
    const all = loadRooms();
    all[code] = entry;
    saveRooms(all);
  }
  nav.show('screen-room-teach');
  showStrip(true, { back: () => nav.home(), backLabel: 'Về màn hình chính' });
  setMode(`LỚP HỌC · ${code}`);
  setStreak(null);
  if (!entry) {
    $('teach-main').hidden = true;
    const d = $('teach-denied');
    d.hidden = false;
    const act = $('teach-denied-act');
    const k = keycap({ tag: 'button', topic: 'neutral', legend: 'Mở phòng mới', legendClass: 'kb-label', variant: 'btn', enter: true });
    k.type = 'button';
    k.addEventListener('click', () => { setUrl(); openRoomNew(); });
    act.replaceChildren(k, el('button', { class: 'btn', type: 'button', text: 'Về màn hình chính', onclick: () => nav.home() }));
    $('teach-denied-t').focus({ preventScroll: true });
    return;
  }
  $('teach-denied').hidden = true;
  $('teach-main').hidden = false;
  buildTeach(code, entry.teacher_key);
  poll = { code, key: entry.teacher_key, timer: null, token: pollToken, fetching: false };
  pollNow();
  $('tp-code').focus({ preventScroll: true });
}

function paintFs() {
  const b = $('tp-fs');
  if (b) b.textContent = document.fullscreenElement ? 'Thoát toàn màn hình' : 'Toàn màn hình';
}

function buildTeach(code, key) {
  // join panel
  const codeEl = $('tp-code');
  codeEl.setAttribute('aria-label', 'Mã phòng ' + code.split('').join(' '));
  codeEl.replaceChildren(...[...code].map((ch, i) => {
    const k = keycap({ topic: TOPICS[i % 4], legend: ch, legendClass: 'legend legend-c' });
    k.setAttribute('aria-hidden', 'true');
    return k;
  }));
  const img = $('tp-qr');
  img.src = api.roomQrUrl(code);
  img.alt = `Mã QR vào phòng ${code}`;
  $('tp-url').textContent = joinHost() + code;
  $('tp-title').textContent = '';
  $('tp-count').replaceChildren();
  $('tp-mock').hidden = !api.isMock;
  $('tp-fs').hidden = !document.documentElement.requestFullscreen;
  paintFs();
  const close = $('tp-close');
  close.disabled = false;
  close.textContent = 'Đóng phòng';

  // heatmap skeleton
  const grid = el('div', { class: 'sk-grid hm-grid', role: 'table', 'aria-label': 'Bản đồ nhiệt của cả lớp: 4 chủ đề, mỗi chủ đề 4 dạng câu đố' });
  grid.append(el('span', { class: 'sk-corner', 'aria-hidden': 'true' }));
  for (const ty of PUZZLE_TYPES) {
    grid.append(el('span', { class: 'pv-label sk-colh', 'aria-hidden': 'true' },
      el('span', { class: 'full', text: TYPE_NAMES[ty] }), el('span', { class: 'short', text: TYPE_SHORT[ty] })));
  }
  const cells = {};
  for (const t of TOPICS) {
    const lab = keycap({ topic: t, legend: el('span', {}, el('span', { class: 'full', text: TOPIC_NAMES[t] }), el('span', { class: 'short', text: TOPIC_GLYPH[t] })), legendClass: 'sk-lab', cls: 'sk-labkey' });
    lab.setAttribute('aria-hidden', 'true');
    grid.append(lab);
    for (const ty of PUZZLE_TYPES) {
      const n = el('b', { class: 'hm-n', text: '–' });
      const pct = el('span', { class: 'hm-pct', 'aria-hidden': 'true' });
      const c = el('div', { class: 'hm-cell', role: 'cell', 'data-lv': '0', 'aria-label': `${TOPIC_NAMES[t]}, ${TYPE_NAMES[ty]}: chưa có dữ liệu` }, n, pct);
      cells[`${t}:${ty}`] = { c, n, pct, v: '' };
      grid.append(c);
    }
  }
  $('tp-grid').replaceChildren(grid);
  teachView = { cells, json: {}, code, key, open: true };

  if (!$('tp-close')._wired) {
    $('tp-close')._wired = true;
    $('tp-close').addEventListener('click', async () => {
      if (!teachView) return;
      const ch = await confirmDialog({
        title: 'Đóng phòng?',
        text: 'Học sinh mới sẽ không vào được nữa. Những người đang chơi vẫn chơi tiếp và bạn vẫn xem được kết quả.',
        buttons: [{ label: 'Đóng phòng', value: 'go', variant: 'primary' }, { label: 'Để mở', value: 'no', variant: 'ghost' }],
      });
      if (ch !== 'go') return;
      try {
        await api.closeRoom(teachView.code, teachView.key);
        paintOpen(false);
        pollNow();
      } catch (e) {
        toast('Không đóng được phòng: ' + e.message);
      }
    });
    $('tp-del').addEventListener('click', async () => {
      if (!teachView) return;
      const { code: c, key: k } = teachView;
      const ch = await confirmDialog({
        title: 'Xoá dữ liệu phòng?',
        text: 'Toàn bộ kết quả của phòng này sẽ bị xoá và không khôi phục được.',
        buttons: [{ label: 'Xoá dữ liệu', value: 'go', variant: 'danger' }, { label: 'Giữ lại', value: 'no', variant: 'ghost' }],
      });
      if (ch !== 'go') return;
      try {
        await api.deleteRoom(c, k);
      } catch (e) {
        if (e.status !== 404) {
          toast('Không xoá được phòng: ' + e.message);
          return;
        }
      }
      const all = loadRooms();
      delete all[c];
      saveRooms(all);
      toast('Đã xoá dữ liệu phòng.');
      nav.home();
    });
    $('tp-fs').addEventListener('click', () => {
      if (document.fullscreenElement) document.exitFullscreen?.();
      else document.documentElement.requestFullscreen?.().catch(() => toast('Trình duyệt không cho phép toàn màn hình.'));
    });
  }
  renderEmpty();
}

function paintOpen(open) {
  teachView.open = open;
  const close = $('tp-close');
  close.disabled = !open;
  close.textContent = open ? 'Đóng phòng' : 'Phòng đã đóng';
  $('tp-title').textContent = (teachView.title ? teachView.title + ' · ' : '') + (open ? LEVEL_NAME[teachView.level] || '' : 'ĐÃ ĐÓNG');
}

function renderEmpty() {
  $('tp-empty').hidden = false;
  $('tp-mist').replaceChildren(el('p', { class: 'tp-none', text: 'Chưa có lỗi nào.' }));
  $('tp-uns').replaceChildren(el('li', { class: 'tp-none', text: 'Chưa có câu nào bị bỏ lại.' }));
  $('tp-players').replaceChildren(el('li', { class: 'tp-none', text: 'Chưa có ai vào phòng.' }));
  $('tp-recent').replaceChildren(el('li', { class: 'tp-none', text: 'Chưa có hoạt động.' }));
  $('tp-count').replaceChildren(el('b', { text: '0' }), ' người đã vào');
}

function setSync(state) {
  const led = $('tp-sync-led');
  const t = $('tp-sync-t');
  const bad = state === 'error';
  led.style.setProperty('--c', bad ? 'var(--crash)' : 'var(--ok)');
  led.classList.toggle('on', true);
  $('tp-sync').classList.toggle('is-busy', state === 'busy');
  $('tp-sync').classList.toggle('is-bad', bad);
  t.textContent = bad ? 'mất kết nối, đang thử lại' : 'đang cập nhật';
}

function pollNow() {
  if (!poll) return;
  clearTimeout(poll.timer);
  tick(poll);
}

async function tick(p) {
  if (p !== poll || p.token !== pollToken) return;
  if ($('screen-room-teach').hidden) {
    stopPoll();
    return;
  }
  const next = () => {
    if (p === poll) p.timer = setTimeout(() => tick(p), POLL_MS);
  };
  if (document.hidden) return next(); // paused; visibilitychange resumes immediately
  setSync('busy');
  try {
    const s = await api.roomSummary(p.code, p.key);
    if (p !== poll) return;
    renderSummary(s);
    setSync('ok');
  } catch (e) {
    if (p !== poll) return;
    if (e.status === 403 || e.status === 404) {
      stopPoll();
      $('tp-sync-t').textContent = e.status === 403 ? 'khoá phòng không đúng trên máy này' : 'phòng không còn tồn tại';
      $('tp-sync-led').style.setProperty('--c', 'var(--crash)');
      $('tp-sync').classList.remove('is-busy');
      return;
    }
    setSync('error');
  }
  next();
}

const same = (k, v) => {
  const s = JSON.stringify(v);
  if (teachView.json[k] === s) return true;
  teachView.json[k] = s;
  return false;
};

function chip(topic, text) {
  return el('span', { class: 'chip t-' + (TOPIC_NAMES[topic] ? topic : 'neutral'), text: text || TOPIC_NAMES[topic] || 'Chung' });
}

export function agoText(s) {
  s = Math.max(0, Math.round(Number(s) || 0));
  if (s < 5) return 'vừa xong';
  if (s < 60) return `${s} giây trước`;
  if (s < 3600) return `${Math.floor(s / 60)} phút trước`;
  return `${Math.floor(s / 3600)} giờ trước`;
}

function renderSummary(s) {
  if (!teachView) return;
  teachView.level = s.level;
  teachView.title = s.title || '';
  if (!same('meta', [s.title, s.level, s.open])) paintOpen(!!s.open);
  const answers = s.totals?.answers || 0;
  $('tp-empty').hidden = answers > 0;

  const nPlayers = s.totals?.players ?? s.players?.length ?? 0;
  if (!same('count', nPlayers)) {
    $('tp-count').replaceChildren(el('b', { text: String(nPlayers) }), ' người đã vào');
  }

  // heatmap
  for (const t of TOPICS) {
    for (const ty of PUZZLE_TYPES) {
      const ref = teachView.cells[`${t}:${ty}`];
      const g = s.grid?.[t]?.[ty] || { answers: 0, correct: 0 };
      const v = `${g.correct}/${g.answers}`;
      if (ref.v === v) continue;
      const first = ref.v === '';
      ref.v = v;
      const rate = g.answers ? g.correct / g.answers : null;
      const lv = rate == null ? '0' : rate < 0.5 ? 'crash' : rate < 0.8 ? 'warn' : 'ok';
      ref.c.dataset.lv = lv;
      ref.n.textContent = g.answers ? v : '–';
      ref.pct.textContent = g.answers ? Math.round(rate * 100) + '%' : '';
      ref.c.setAttribute('aria-label', g.answers
        ? `${TOPIC_NAMES[t]}, ${TYPE_NAMES[ty]}: ${g.correct} trên ${g.answers} đúng`
        : `${TOPIC_NAMES[t]}, ${TYPE_NAMES[ty]}: chưa có dữ liệu`);
      if (!first && g.answers) {
        anim(ref.c, [{ filter: 'brightness(1)' }, { filter: 'brightness(1.7)', offset: 0.3 }, { filter: 'brightness(1)' }], { duration: 700 });
      }
    }
  }

  // top mistakes
  if (!same('mist', s.top_mistakes)) {
    const list = s.top_mistakes || [];
    if (!list.length) {
      $('tp-mist').replaceChildren(el('p', { class: 'tp-none', text: 'Chưa có lỗi nào.' }));
    } else {
      const [top, ...rest] = list;
      $('tp-mist').replaceChildren(
        el('div', { class: 'mist-top t-' + (TOPIC_NAMES[top.topic] ? top.topic : 'neutral') },
          el('p', { class: 'mist-label', text: top.label }),
          el('div', { class: 'mist-meta' },
            el('b', { class: 'mist-count', text: '×' + top.count }),
            chip(top.topic),
            el('span', { class: 'mist-who', text: `${top.players} người` }))),
        rest.length ? el('ol', { class: 'mist-list' }, ...rest.slice(0, 4).map((m) =>
          el('li', {}, el('span', { class: 'mist-l', text: m.label }), chip(m.topic), el('b', { class: 'mist-c', text: '×' + m.count })))) : null);
    }
  }

  // unsolved
  if (!same('uns', s.unsolved)) {
    const list = (s.unsolved || []).slice(0, 5);
    $('tp-uns').replaceChildren(...(list.length
      ? list.map((u) => el('li', { class: 'uns-item' },
          el('p', { class: 'uns-prompt', text: u.prompt }),
          el('div', { class: 'uns-meta' }, chip(u.topic), el('span', { text: `${u.attempts} lượt thử · ${u.players} người` }))))
      : [el('li', { class: 'tp-none', text: 'Chưa có câu nào bị bỏ lại.' })]));
  }

  // leaderboard
  if (!same('players', s.players)) {
    const list = [...(s.players || [])].sort((a, b) => b.score - a.score || b.correct - a.correct);
    const STATUS = { playing: ['ok', 'đang chơi'], nofit: ['warn', 'hết chỗ'], crash: ['crash', 'đã sập'] };
    $('tp-players').replaceChildren(...(list.length
      ? list.map((p, i) => {
          const stale = p.last_seen_s > STALE_S;
          const [color, word] = STATUS[p.status] || STATUS.playing;
          return el('li', { class: 'pl-row' + (stale ? ' is-stale' : '') },
            el('span', { class: 'pl-rank', text: String(i + 1) }),
            el('span', { class: 'pl-led' }, el('i', { class: 'led' + (stale ? '' : ' on'), style: { '--c': `var(--${color})` } }),
              el('span', { class: 'sr-only', text: stale ? 'không hoạt động' : word })),
            el('span', { class: 'pl-name', text: p.nickname }),
            el('span', { class: 'pl-ok' }, icon('check', { size: 14 }), `${p.correct}/${p.answers}`),
            el('b', { class: 'pl-score', text: String(p.score) }),
            p.player_id ? el('button', { class: 'pl-hide', type: 'button', 'aria-label': `Ẩn ${p.nickname} khỏi phòng`, text: 'Ẩn', onclick: (ev) => hidePlayer(p, ev.currentTarget.closest('.pl-row')) }) : null);
        })
      : [el('li', { class: 'tp-none', text: 'Chưa có ai vào phòng.' })]));
  }

  // recent activity (ago text changes every poll, so always re-render)
  const rec = (s.recent || []).slice(0, 8);
  $('tp-recent').replaceChildren(...(rec.length
    ? rec.map((r) => el('li', { class: 'rc-item ' + (r.correct ? 'is-ok' : 'is-bad') },
        el('span', { class: 'rc-mark' }, icon(r.correct ? 'check' : 'x', { size: 16 }), el('span', { class: 'sr-only', text: r.correct ? 'đúng' : 'sai' })),
        el('b', { class: 'rc-name', text: r.nickname }),
        el('span', { class: 'rc-what', text: [TOPIC_NAMES[r.topic], TYPE_SHORT[r.type] && TYPE_NAMES[r.type], !r.correct && r.mistake_label].filter(Boolean).join(' · ') }),
        el('span', { class: 'rc-ago', text: agoText(r.ago_s) })))
    : [el('li', { class: 'tp-none', text: 'Chưa có hoạt động.' })]));
}

async function hidePlayer(p, row) {
  if (!teachView) return;
  const { code, key } = teachView;
  const ch = await confirmDialog({
    title: 'Ẩn người chơi?',
    text: `Ẩn ${p.nickname} khỏi phòng? Người này sẽ không được tính nữa.`,
    buttons: [{ label: 'Ẩn người chơi', value: 'go', variant: 'danger' }, { label: 'Giữ lại', value: 'no', variant: 'ghost' }],
  });
  if (ch !== 'go') return;
  try {
    await api.kickPlayer(code, p.player_id, key);
  } catch (e) {
    if (e.status !== 404) {
      toast('Không ẩn được người chơi: ' + e.message);
      return;
    }
  }
  if (row?.isConnected) row.remove();
  if (!$('tp-players').children.length) $('tp-players').append(el('li', { class: 'tp-none', text: 'Chưa có ai vào phòng.' }));
  teachView.json.players = null; // next poll re-renders from the server list
  toast(`Đã ẩn ${p.nickname}.`);
  pollNow();
}

// ---- student: join -------------------------------------------------------------------------------
export async function openJoin(code) {
  code = String(code || '').toUpperCase();
  nav.show('screen-room-join');
  showStrip(true, { back: () => nav.home(), backLabel: 'Về màn hình chính' });
  setMode('LỚP HỌC · ' + code);
  setStreak(null);
  $('rj-code').textContent = 'PHÒNG ' + code;
  $('rj-title').textContent = 'Vào phòng';
  $('rj-sub').textContent = 'Đang tìm phòng…';
  showErr('rj-err', '');
  const act = $('rj-act');
  if (!act.firstChild) act.append(submitKey('Vào phòng'));
  const key = act.firstChild;
  key.disabled = true;
  const input = $('rj-nick');
  $('rj-free').hidden = true;
  $('rj-random').hidden = true;
  $('rj-got').hidden = true;
  const prev = getStudent();
  if (prev && prev.code === code) input.value = prev.nickname;
  const form = $('room-join-form');
  form._code = code;
  let info = null;
  const mine = (form._tok = (form._tok || 0) + 1);

  if (!form._wired) {
    form._wired = true;
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      if (key.disabled || !form._info) return;
      const free = form._info.names === 'free';
      const tok = form._tok;
      const nickname = free ? input.value.trim() : '';
      if (free && !nickname) {
        showErr('rj-err', 'Hãy nhập một biệt danh.');
        input.focus();
        return;
      }
      setBusy(key, true, 'Vào phòng');
      showErr('rj-err', '');
      try {
        const r = await api.joinRoom(form._code, nickname);
        const name = r.nickname || nickname;
        setStudent({ code: form._code, player_token: r.player_token, nickname: name, level: r.level });
        setUrl({ room: form._code });
        if (!free && name) {
          // random mode: show the assigned name for a moment before the game starts
          const got = $('rj-got');
          got.replaceChildren('Tên của bạn: ', el('b', { text: name }));
          got.hidden = false;
          await wait(1400);
          if (form._tok !== tok) return;
        }
        nav.play(r.level || form._info.level);
      } catch (err) {
        const msg = { 404: 'Không tìm thấy phòng', 410: 'Phòng đã đóng', 409: 'Phòng đã đủ người' }[err.status] || (err.status === 422 ? err.message || 'Biệt danh này không được dùng. Hãy chọn tên khác.' : err.message);
        showErr('rj-err', msg);
        if (err.status === 404 || err.status === 410 || err.status === 409) key.disabled = true;
        else setBusy(key, false, 'Vào phòng');
        return;
      }
      setBusy(key, false, 'Vào phòng');
    });
  }
  form._info = null;

  try {
    info = await api.getRoom(code);
  } catch (err) {
    if (mine !== form._tok) return;
    $('rj-sub').textContent = '';
    showErr('rj-err', err.status === 404 ? 'Không tìm thấy phòng' : err.status === 410 ? 'Phòng đã đóng' : 'Không tải được phòng: ' + err.message);
    $('rj-title').focus({ preventScroll: true });
    return;
  }
  if (mine !== form._tok) return;
  form._info = info;
  $('rj-title').textContent = info.title || 'Vào phòng';
  $('rj-sub').textContent = `Cấp độ ${LEVEL_NAME[info.level] || info.level} · Code Rescue · ${info.players} người đã vào`;
  if (info.open === false) {
    showErr('rj-err', 'Phòng đã đóng');
    $('rj-title').focus({ preventScroll: true });
    return;
  }
  const free = info.names === 'free';
  $('rj-free').hidden = !free;
  $('rj-random').hidden = free;
  key.disabled = false;
  if (free) input.focus({ preventScroll: true });
  else key.focus({ preventScroll: true });
}

// ---- student: progress reporting -------------------------------------------------------------------
const rep = { sentKey: '', lastAt: 0, timer: null, pending: null };

function flush() {
  clearTimeout(rep.timer);
  rep.timer = null;
  const s = getStudent();
  const p = rep.pending;
  if (!s || !p) return;
  rep.pending = null;
  rep.lastAt = Date.now();
  rep.sentKey = JSON.stringify(p);
  api.roomProgress(s.code, { player_token: s.player_token, ...p }).catch(() => {});
}

/** G = the Code Rescue game state. Sends on change, at most every 2 s; the final state is sent at once. */
export function reportProgress(G, { force = false } = {}) {
  if (!getStudent() || !G) return;
  const over = G.phase === 'over';
  const snap = { score: G.score | 0, status: over ? (G.endReason === 'crash' ? 'crash' : 'nofit') : 'playing', bugs_fixed: G.bugsFixed | 0 };
  if (!force && JSON.stringify(snap) === rep.sentKey && !rep.pending) return;
  rep.pending = snap;
  if (force || over) return flush();
  if (!rep.timer) rep.timer = setTimeout(flush, Math.max(0, 2000 - (Date.now() - rep.lastAt)));
}

/** New game in the same room: let the next report go out immediately. */
export function resetProgress() {
  clearTimeout(rep.timer);
  rep.timer = null;
  rep.pending = null;
  rep.sentKey = '';
  rep.lastAt = 0;
}
