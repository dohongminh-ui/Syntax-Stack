// API client. Relative paths only. Never assumes answers.
// When the URL has ?mock=1 every call is routed to mock-api.js instead.
import { lang } from './i18n.js';

export const isMock = new URLSearchParams(location.search).get('mock') === '1';

let mockMod = null;
async function mock() {
  mockMod = mockMod || (await import('./mock-api.js'));
  return mockMod;
}

// Every request has a deadline so a slow server never leaves a loading state on screen forever.
// Tutor-backed calls get longer: the server itself gives the tutor up to 38 s before falling back.
const TIMEOUT_MS = 15000;
const TUTOR_TIMEOUT_MS = 45000;

async function request(method, url, body, { timeout = TIMEOUT_MS, headers = null, raw = false } = {}) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeout);
  let res;
  try {
    res = await fetch(url, {
      method,
      // X-Lang tells the server which language to answer in (puzzle text, hints, errors, Misaki lines): 'vi' or 'en'.
      headers: { ...(body ? { 'Content-Type': 'application/json' } : {}), 'X-Lang': lang(), ...(headers || {}) },
      body: body ? JSON.stringify(body) : undefined,
      signal: ctrl.signal,
    });
  } catch (e) {
    throw new Error(e.name === 'AbortError' ? 'Máy chủ phản hồi quá lâu. Thử lại sau.' : 'Không kết nối được máy chủ.');
  } finally {
    clearTimeout(timer);
  }
  if (!res.ok) {
    let detail = '';
    try {
      detail = (await res.json()).detail;
    } catch {
      /* ignore */
    }
    const err = new Error(typeof detail === 'string' && detail ? detail : 'Lỗi máy chủ (' + res.status + ')');
    err.status = res.status;
    throw err;
  }
  if (raw || res.status === 204) return null;
  return res.json();
}

export async function health() {
  return isMock ? (await mock()).health() : request('GET', '/api/health');
}

// While a ranked / race run is in progress, every next-puzzle, hint and answer call carries run_id + run_token
// (body for POST, query for GET). main.js sets it when the run starts (ranked.js) and clears it the moment the game ends.
let runCtx = null;
export function setRunContext(ctx) {
  runCtx = ctx && ctx.id && ctx.token ? { run_id: ctx.id, run_token: ctx.token } : null;
}

// While a live 1v1 match (Đối kháng) is in progress, the same three calls carry match_id + match_token instead.
let matchCtx = null;
export function setMatchContext(ctx) {
  matchCtx = ctx && ctx.id && ctx.token ? { match_id: ctx.id, match_token: ctx.token } : null;
}

export async function nextPuzzle(params) {
  if (runCtx) params = { ...params, ...runCtx };
  if (matchCtx) params = { ...params, ...matchCtx };
  if (isMock) return (await mock()).nextPuzzle(params);
  return request('POST', '/api/puzzle/next', params);
}

// While a student is in a live classroom, every answer carries the room code + player token.
let roomCtx = null;
export function setRoomContext(ctx) {
  roomCtx = ctx && ctx.code && ctx.player_token ? { room: ctx.code, player_token: ctx.player_token } : null;
}

// `room: false` (standalone practice) skips both the room fields and the run fields.
export async function submitAnswer(id, body, { room = true } = {}) {
  if (roomCtx && room) body = { ...body, ...roomCtx };
  if (runCtx && room) body = { ...body, ...runCtx };
  if (matchCtx && room) body = { ...body, ...matchCtx };
  if (isMock) return (await mock()).submitAnswer(id, body);
  return request('POST', '/api/puzzle/' + encodeURIComponent(id) + '/answer', body);
}

export async function getHint(id, level) {
  if (isMock) return (await mock()).getHint(id, level, matchCtx);
  const run = runCtx ? '&run_id=' + encodeURIComponent(runCtx.run_id) + '&run_token=' + encodeURIComponent(runCtx.run_token) : '';
  const match = matchCtx ? '&match_id=' + encodeURIComponent(matchCtx.match_id) + '&match_token=' + encodeURIComponent(matchCtx.match_token) : '';
  return request('GET', '/api/puzzle/' + encodeURIComponent(id) + '/hint?level=' + level + run + match);
}

export async function explainChoice(id, body) {
  if (isMock) {
    const result = await (await mock()).submitAnswer(id, { ...body, reveal: true });
    return { text: result.explanation || result.message, source: 'canned' };
  }
  return request('POST', '/api/puzzle/' + encodeURIComponent(id) + '/explain', body, { timeout: TUTOR_TIMEOUT_MS });
}

export async function rematch(id, level) {
  if (isMock) return (await mock()).rematch(id, level);
  return request('GET', '/api/puzzle/' + encodeURIComponent(id) + '/rematch?level=' + encodeURIComponent(level), null, { timeout: TUTOR_TIMEOUT_MS });
}

// ---- Syntax Rows ----
export async function rowsLevels() {
  if (isMock) return (await mock()).rowsLevels();
  return request('GET', '/api/rows/levels');
}

export async function rowsLevel(id) {
  if (isMock) return (await mock()).rowsLevel(id);
  return request('GET', '/api/rows/levels/' + encodeURIComponent(id));
}

export async function rowsRun(id, body) {
  if (isMock) {
    const result = await (await mock()).rowsRun(id, body);
    if (body.prediction != null) {
      result.prediction = { correct: result.actual_output == null ? null : body.prediction.trimEnd() === result.actual_output };
    }
    return result;
  }
  return request('POST', '/api/rows/levels/' + encodeURIComponent(id) + '/run', body);
}

export function rowsPractice(id) {
  return request('GET', '/api/rows/levels/' + encodeURIComponent(id) + '/practice');
}

export function rowsTwist(id, body) {
  return request('POST', '/api/rows/levels/' + encodeURIComponent(id) + '/twist', body);
}

export function teachBack(id, body) {
  if (isMock) return Promise.resolve({ text: 'Nếu đổi một mảnh mã, đầu ra sẽ thay đổi thế nào?', source: 'canned' });
  return request('POST', '/api/rows/levels/' + encodeURIComponent(id) + '/teach-back', body, { timeout: TUTOR_TIMEOUT_MS });
}

/** Tutor explains why a wrong output prediction differs from the real output. body: { rows, prediction } */
export async function explainPrediction(id, body) {
  if (isMock) {
    const m = await mock();
    const run = await m.rowsRun(id, { rows: body.rows });
    return m.explainPrediction(body.prediction, run.actual_output);
  }
  return request('POST', '/api/rows/levels/' + encodeURIComponent(id) + '/explain-prediction', body, { timeout: TUTOR_TIMEOUT_MS });
}

/** End-of-run tutor summary. body: { level, mode, end_reason, wrong: [...] } */
export async function debrief(body) {
  if (isMock) return (await mock()).debrief(body);
  return request('POST', '/api/rescue/debrief', body, { timeout: TUTOR_TIMEOUT_MS });
}

export async function rowsHint(id, level, errorGroup, attempt) {
  if (isMock) return (await mock()).rowsHint(id, level, errorGroup);
  const path = '/api/rows/levels/' + encodeURIComponent(id) + '/hint?level=' + level;
  if (attempt) return request('POST', path, attempt, { timeout: TUTOR_TIMEOUT_MS });
  return request('GET', path + (errorGroup ? '&error_group=' + encodeURIComponent(errorGroup) : ''));
}

// ---- Custom puzzle sets (pasted code) ----
const CUSTOM_TIMEOUT_MS = 30000;

/** body: { code, level? } -> { id, topic, code, expected_output, puzzles, skipped }. Errors carry `.status` (422, 429...). */
export async function createCustomSet(body) {
  if (isMock) return (await mock()).createCustomSet(body);
  return request('POST', '/api/custom/sets', body, { timeout: CUSTOM_TIMEOUT_MS });
}

export async function getCustomSet(id, level) {
  if (isMock) return (await mock()).getCustomSet(id, level);
  return request('GET', '/api/custom/sets/' + encodeURIComponent(id) + (level ? '?level=' + encodeURIComponent(level) : ''));
}

// ---- Chat with Misaki (docs/misaki-chat.md) ----
const MISAKI_PUZZLE_TIMEOUT_MS = 75000; // tutor (up to ~38 s) + the sandbox that builds the set

/** body: { messages: [{role: 'user'|'misaki', text}], context?: { level, weak_topics } } -> { text, source, mood, action }. */
export async function misakiChat(body) {
  if (isMock) return (await mock()).misakiChat(body);
  return request('POST', '/api/misaki/chat', body, { timeout: TUTOR_TIMEOUT_MS });
}

/** body: { topic, idea, level } -> { set, source: 'ai'|'canned', note }. `set` has the custom-set shape. 429 = rate limited. */
export async function misakiPuzzle(body) {
  if (isMock) return (await mock()).misakiPuzzle(body);
  return request('POST', '/api/misaki/puzzle', body, { timeout: MISAKI_PUZZLE_TIMEOUT_MS });
}

// ---- Live classroom ----
const keyHeader = (key) => ({ 'X-Teacher-Key': key });
const room = (code) => '/api/rooms/' + encodeURIComponent(code);

/** body: { level, title?, names?: 'random'|'free' } -> { code, teacher_key, join_url, level, title, names }. 429 = rate limited. */
export async function createRoom(body) {
  if (isMock) return (await mock()).createRoom(body);
  return request('POST', '/api/rooms', body);
}

export async function getRoom(code) {
  if (isMock) return (await mock()).getRoom(code);
  return request('GET', room(code));
}

/** Random-names room: `nickname` is omitted and the server assigns one. -> { player_id, player_token, nickname, level }. 409 full, 410 closed, 404, 422 filtered name (free mode). */
export async function joinRoom(code, nickname) {
  if (isMock) return (await mock()).joinRoom(code, nickname);
  return request('POST', room(code) + '/join', nickname ? { nickname } : {});
}

/** Teacher hides a player: 204. That player's token stops working. */
export async function kickPlayer(code, playerId, key) {
  if (isMock) return (await mock()).kickPlayer(code, playerId, key);
  return request('POST', room(code) + '/players/' + encodeURIComponent(playerId) + '/kick', null, { headers: keyHeader(key) });
}

/** body: { player_token, score, status: playing|crash|nofit, bugs_fixed } */
export async function roomProgress(code, body) {
  if (isMock) return null;
  return request('POST', room(code) + '/progress', body, { timeout: 8000 });
}

export async function roomSummary(code, key) {
  if (isMock) return (await mock()).roomSummary(code, key);
  return request('GET', room(code) + '/summary', null, { headers: keyHeader(key), timeout: 8000 });
}

export async function closeRoom(code, key) {
  if (isMock) return (await mock()).closeRoom(code, key);
  return request('POST', room(code) + '/close', {}, { headers: keyHeader(key) });
}

export async function deleteRoom(code, key) {
  if (isMock) return (await mock()).deleteRoom(code, key);
  return request('DELETE', room(code), null, { headers: keyHeader(key) });
}

/** -> { nickname } a random generated name ("Mèo Xanh 42"). 429 when asked too often. */
export async function fetchNickname() {
  if (isMock) return (await mock()).fetchNickname();
  return request('GET', '/api/nickname');
}

// ---- Ranked runs, leaderboard, races (docs/ranked-and-race.md) ----
/** body: { kind: 'ranked'|'race', level, nickname, device_id, race? } -> { run_id, run_token, seed, level, kind, race? }. 404/410 race, 422, 429. */
export async function createRun(body) {
  if (isMock) return (await mock()).createRun(body);
  return request('POST', '/api/runs', body);
}

/** body: { run_token, moves, client_score } -> { status: 'verified', score, locks, mistakes, bugs_fixed, best_streak, duration_s, rank, race? } | { status: 'rejected', reason } */
export async function finishRun(id, body) {
  if (isMock) return (await mock()).finishRun(id, body);
  return request('POST', '/api/runs/' + encodeURIComponent(id) + '/finish', body, { timeout: 30000 });
}

/** -> { level, period, entries: [{ rank, nickname, score, locks, at }], you: { rank, score } | null } */
export async function leaderboard({ level, period, device_id }) {
  if (isMock) return (await mock()).leaderboard({ level, period, device_id });
  const q = new URLSearchParams({ level, period });
  if (device_id) q.set('device_id', device_id);
  return request('GET', '/api/leaderboard?' + q.toString());
}

/** body: { level, nickname, device_id } -> { code, seed, level, url } */
export async function createRace(body) {
  if (isMock) return (await mock()).createRace(body);
  return request('POST', '/api/races', body);
}

/** -> { code, level, created_by, created_at, expires_at, results: [{ rank, nickname, score, locks, mistakes, duration_s, finished_at, you? }], playing }
 *  Sends this browser's device id so the server can mark the player's own row (`you: true`). */
export async function getRace(code) {
  if (isMock) return (await mock()).getRace(code);
  let device = '';
  try { device = localStorage.getItem('syntaxstack.device') || ''; } catch { /* storage blocked */ }
  const q = /^[0-9a-f]{32}$/.test(device) ? '?device_id=' + device : '';
  return request('GET', '/api/races/' + encodeURIComponent(code) + q, null, { timeout: 8000 });
}

export const roomQrUrl =(code) => (isMock ? mockQr(code) : room(code) + '/qr.svg');

// Mock only: a decorative placeholder (not a scannable code), as a data URI.
function mockQr(code) {
  let h = 0;
  for (const ch of code) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  const n = 25;
  let d = '';
  const finder = (x, y) => `M${x} ${y}h7v7h-7zM${x + 1} ${y + 1}v5h5v-5z`;
  for (let y = 0; y < n; y++) {
    for (let x = 0; x < n; x++) {
      const inFinder = (x < 8 && y < 8) || (x > n - 9 && y < 8) || (x < 8 && y > n - 9);
      if (inFinder) continue;
      h = (Math.imul(h, 1664525) + 1013904223) >>> 0;
      if (h >>> 28 < 7) d += `M${x} ${y}h1v1h-1z`;
    }
  }
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="-2 -2 ${n + 4} ${n + 4}" shape-rendering="crispEdges"><rect x="-2" y="-2" width="${n + 4}" height="${n + 4}" fill="#fff"/><path fill="#111" fill-rule="evenodd" d="${finder(0, 0)}${finder(n - 7, 0)}${finder(0, n - 7)}${d}"/></svg>`;
  return 'data:image/svg+xml;utf8,' + encodeURIComponent(svg);
}

// ---- Real-time 1v1 "Đối kháng" (docs/pvp.md). Tickets come from HTTP, the match itself runs over a WebSocket (pvp.js). ----
const duel = (code) => '/api/pvp/private/' + encodeURIComponent(code);

/** body: { level, nickname, device_id } -> { ticket }. Joins the quick-match queue for that level. */
export async function pvpQueue(body) {
  if (isMock) return (await mock()).pvpQueue(body);
  return request('POST', '/api/pvp/queue', body);
}

export async function pvpLeaveQueue(ticket) {
  if (isMock) return (await mock()).pvpLeaveQueue(ticket);
  return request('DELETE', '/api/pvp/queue/' + encodeURIComponent(ticket), null, { timeout: 5000 });
}

/** body: { level, nickname, device_id } -> { code, ticket, url }. */
export async function pvpPrivate(body) {
  if (isMock) return (await mock()).pvpPrivate(body);
  return request('POST', '/api/pvp/private', body);
}

/** body: { nickname, device_id } -> { ticket }. 404 unknown, 409 full, 410 expired, 422 filtered name. */
export async function pvpJoinPrivate(code, body) {
  if (isMock) return (await mock()).pvpJoinPrivate(code, body);
  return request('POST', duel(code) + '/join', body);
}

/** body: { level, nickname, device_id, misaki: 1..4, training: bool } -> { ticket }. An immediate match against Misaki. 403: that level is still locked. */
export async function pvpBot(body) {
  if (isMock) return (await mock()).pvpBot(body);
  return request('POST', '/api/pvp/bot', body);
}

/** The Misaki ladder for this device -> { unlocked: n, wins: { "1": k }, games: { "1": k } }. */
export async function pvpMisaki(deviceId) {
  if (isMock) return (await mock()).pvpMisaki(deviceId);
  return request('GET', '/api/pvp/misaki?device_id=' + encodeURIComponent(deviceId), null, { timeout: 8000 });
}

/** A WebSocket-shaped object for GET /api/pvp/ws?ticket=... (the mock returns a same-shaped fake server). */
export async function openPvpSocket(ticket) {
  if (isMock) return new (await mock()).MockPvpSocket(ticket);
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  return new WebSocket(`${proto}//${location.host}/api/pvp/ws?ticket=${encodeURIComponent(ticket)}&lang=${lang()}`);
}
