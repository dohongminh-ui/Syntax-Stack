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

/** The (up to `limit`) topics the learner got wrong most often in the last 40 mistakes, most frequent first. Sent to Misaki as a hint. */
export function weakTopics(topics, limit = 4) {
  const counts = new Map();
  for (const entry of practiceHistory()) if (topics.includes(entry?.topic)) counts.set(entry.topic, (counts.get(entry.topic) || 0) + 1);
  return [...counts.keys()].sort((a, b) => counts.get(b) - counts.get(a)).slice(0, limit);
}

// ---- Skill map: per-template outcomes of Code Rescue bank puzzles ----
const SKILLS_KEY = 'syntaxstack.skills';
const SKILLS_SEEN_KEY = 'syntaxstack.skills.seen';

/** { [templateId]: { topic, type, attempts, correct, recent: boolean[<=6], lastWrongPrompt, updatedAt } } */
export function loadSkills() {
  try {
    const v = JSON.parse(localStorage.getItem(SKILLS_KEY));
    return v && typeof v === 'object' && !Array.isArray(v) ? v : {};
  } catch {
    return {};
  }
}

export function recordSkill({ templateId, topic, type, correct, prompt = '' }) {
  if (!templateId || templateId === 'custom' || !topic || !type) return;
  try {
    const all = loadSkills();
    const e = all[templateId] || { topic, type, attempts: 0, correct: 0, recent: [], lastWrongPrompt: '', updatedAt: 0 };
    e.topic = topic;
    e.type = type;
    e.attempts += 1;
    if (correct) e.correct += 1;
    e.recent = [...(Array.isArray(e.recent) ? e.recent : []), !!correct].slice(-6);
    if (!correct && prompt) e.lastWrongPrompt = String(prompt).slice(0, 300);
    e.updatedAt = Date.now();
    all[templateId] = e;
    localStorage.setItem(SKILLS_KEY, JSON.stringify(all));
  } catch {
    /* ignore */
  }
}

/** Mastery levels shown the last time the map was opened: { 'topic:type': 0..3 }. */
export function loadSkillsSeen() {
  try {
    const v = JSON.parse(localStorage.getItem(SKILLS_SEEN_KEY));
    return v && typeof v === 'object' && !Array.isArray(v) ? v : {};
  } catch {
    return {};
  }
}

export function saveSkillsSeen(levels) {
  try {
    localStorage.setItem(SKILLS_SEEN_KEY, JSON.stringify(levels));
  } catch {
    /* ignore */
  }
}

const MISAKI_LANGUAGE_KEY = 'syntaxstack.misaki.language';

export function loadMisakiLanguage() {
  try { return localStorage.getItem(MISAKI_LANGUAGE_KEY); } catch { return null; }
}

export function saveMisakiLanguage(language) {
  try { localStorage.setItem(MISAKI_LANGUAGE_KEY, language); } catch { /* keep the choice in memory */ }
}

// ---- Chat with Misaki: which body her model shows ('chibi' is the default, 'normal' the tall form) ----
const BODY_KEY = 'syntaxstack.misaki.body';

export function loadMisakiBody() {
  try {
    return localStorage.getItem(BODY_KEY) === 'normal' ? 'normal' : 'chibi';
  } catch {
    return 'chibi';
  }
}

export function saveMisakiBody(name) {
  try {
    localStorage.setItem(BODY_KEY, name === 'normal' ? 'normal' : 'chibi');
  } catch {
    /* ignore */
  }
}

// ---- Chat with Misaki: is her stage panel hidden? (default: shown) ----
const STAGE_KEY = 'syntaxstack.misaki.stage';

export function loadMisakiStageHidden() {
  try {
    return localStorage.getItem(STAGE_KEY) === 'hidden';
  } catch {
    return false;
  }
}

export function saveMisakiStageHidden(hidden) {
  try {
    localStorage.setItem(STAGE_KEY, hidden ? 'hidden' : 'shown');
  } catch {
    /* ignore */
  }
}
