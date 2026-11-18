// Misaki: the game's AI character (docs/pvp.md section 5). One identity, used by the tutor card, the PvP ladder,
// the opponent panel, the coach bubble and the end screen: a mustard keycap with the legend "M", plus her name.
import { keycap } from './keycap.js';

export const MISAKI = 'Misaki';
export const LADDER = [
  { level: 1, name: 'Tập sự' },
  { level: 2, name: 'Khá' },
  { level: 3, name: 'Giỏi' },
  { level: 4, name: 'Bậc thầy' },
];

export const ladderName = (n) => LADDER.find((l) => l.level === Number(n))?.name || '';
/** "Misaki · Giỏi" */
export const misakiTitle = (n) => (ladderName(n) ? `${MISAKI} · ${ladderName(n)}` : MISAKI);

/** The avatar: a small mustard keycap "M". Decorative (the name is always printed next to it). */
export function misakiAvatar({ cls = '' } = {}) {
  const k = keycap({ topic: 'conditions', legend: 'M', legendClass: 'legend legend-c', cls: ('misaki-av ' + cls).trim() });
  k.setAttribute('aria-hidden', 'true');
  return k;
}
