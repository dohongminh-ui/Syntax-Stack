// Seeded RNG. mulberry32, exactly as the server replays it (docs/ranked-and-race.md section 2).
// Do not change the arithmetic: 32-bit int maths, Math.imul, >>> 0, divide by 4294967296.
export function mulberry(a) {
  return () => {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
