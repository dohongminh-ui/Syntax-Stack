// API client. Relative paths only. Never assumes answers.
// When the URL has ?mock=1 every call is routed to mock-api.js instead.
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

async function request(method, url, body, { timeout = TIMEOUT_MS } = {}) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeout);
  let res;
  try {
    res = await fetch(url, {
      method,
      headers: body ? { 'Content-Type': 'application/json' } : undefined,
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
    throw new Error(typeof detail === 'string' && detail ? detail : 'Lỗi máy chủ (' + res.status + ')');
  }
  return res.json();
}

export async function health() {
  return isMock ? (await mock()).health() : request('GET', '/api/health');
}

export async function nextPuzzle(params) {
  if (isMock) return (await mock()).nextPuzzle(params);
  return request('POST', '/api/puzzle/next', params);
}

export async function submitAnswer(id, body) {
  if (isMock) return (await mock()).submitAnswer(id, body);
  return request('POST', '/api/puzzle/' + encodeURIComponent(id) + '/answer', body);
}

export async function getHint(id, level) {
  if (isMock) return (await mock()).getHint(id, level);
  return request('GET', '/api/puzzle/' + encodeURIComponent(id) + '/hint?level=' + level);
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
