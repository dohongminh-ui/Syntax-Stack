// localStorage helpers. Every access is wrapped: storage may be blocked.
const HS_KEY = 'syntaxstack.rescue.highscore';
const PREF_KEY = 'syntaxstack.rescue.prefs';

export function getHighScore() {
  try {
    return Number(localStorage.getItem(HS_KEY)) || 0;
  } catch {
    return 0;
  }
}

export function setHighScore(n) {
  try {
    if (n > getHighScore()) localStorage.setItem(HS_KEY, String(n));
  } catch {
    /* ignore */
  }
}

export function loadPrefs() {
  try {
    return JSON.parse(localStorage.getItem(PREF_KEY)) || {};
  } catch {
    return {};
  }
}

export function savePrefs(p) {
  try {
    localStorage.setItem(PREF_KEY, JSON.stringify(p));
  } catch {
    /* ignore */
  }
}

// ---- Syntax Rows progress: { r1: { stars, score }, ... } ----
const ROWS_KEY = 'syntaxstack.rows.progress';

export function loadRowsProgress() {
  try {
    const v = JSON.parse(localStorage.getItem(ROWS_KEY));
    return v && typeof v === 'object' ? v : {};
  } catch {
    return {};
  }
}

export function saveRowsProgress(all) {
  try {
    localStorage.setItem(ROWS_KEY, JSON.stringify(all));
  } catch {
    /* ignore */
  }
}

/** Keeps the best stars and score per level. Returns the updated progress map. */
export function recordRowsResult(id, stars, score) {
  const all = loadRowsProgress();
  const prev = all[id] || { stars: 0, score: 0 };
  all[id] = { stars: Math.max(prev.stars, stars), score: Math.max(prev.score, score) };
  saveRowsProgress(all);
  return all;
}

const PRACTICE_KEY = 'syntaxstack.practice.mistakes';

function practiceHistory() {
  try {
    const value = JSON.parse(localStorage.getItem(PRACTICE_KEY));
    return Array.isArray(value) ? value : [];
  } catch {
    return [];
  }
}

export function recordMistake(mistake) {
  try {
    localStorage.setItem(PRACTICE_KEY, JSON.stringify([...practiceHistory(), mistake].slice(-40)));
  } catch {
    /* ignore */
  }
}

export function practiceFocus(topics) {
  const recent = practiceHistory().reverse().filter((entry) => topics.includes(entry?.topic));
  const counts = new Map();
  for (const entry of recent) counts.set(entry.topic, (counts.get(entry.topic) || 0) + 1);
  const topic = [...counts.keys()].sort((a, b) => counts.get(b) - counts.get(a))[0];
  const rows = recent.find((entry) => entry.topic === topic && entry.levelId);
  return {
    topic,
    count: counts.get(topic) || 0,
    levelId: rows?.levelId,
    errorGroup: rows?.errorGroup,
    rows: rows?.rows,
    puzzleId: recent.find((entry) => entry.topic === topic && entry.puzzleId)?.puzzleId,
  };
}
