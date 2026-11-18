// Small presentation helpers shared by the leaderboard, the race lobby and the end screen.
import { keycap } from './keycap.js';

export const fmtTime = (s) => {
  s = Math.max(0, Math.round(Number(s) || 0));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
};

export const fmtScore = (n) => String(Math.round(Number(n) || 0));

export const LEVEL_NAME = { beginner: 'Beginner', intermediate: 'Intermediate', advanced: 'Advanced' };

const MEDAL = { 1: 'gold', 2: 'silver', 3: 'bronze' };
const MEDAL_WORD = { 1: 'hạng nhất', 2: 'hạng nhì', 3: 'hạng ba' };

/** Rank cell: 1-3 as a gold / silver / bronze keycap, the rest as a mono number. */
export function rankMark(n) {
  const medal = MEDAL[n];
  if (!medal) {
    const s = document.createElement('span');
    s.className = 'rk-num';
    s.textContent = String(n);
    return s;
  }
  const k = keycap({ tag: 'span', topic: 'neutral', legend: String(n), legendClass: 'legend legend-c', cls: 'rk-medal rk-' + medal });
  k.setAttribute('role', 'img');
  k.setAttribute('aria-label', `${MEDAL_WORD[n]}`);
  return k;
}
