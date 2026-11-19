// Pure translation core (no DOM, no imports): Vietnamese string -> English using the dictionary in i18n-en.js.
// Shared by the runtime (i18n.js) and the coverage check (tools/i18n-coverage.mjs).
//
// Lookup order for one string:
//   1. exact match in EN (trimmed text, then whitespace-collapsed)
//   2. "# " / "· " prefixes (code-comment style lines and fragments) are peeled off and the rest is translated
//   3. EN_PATTERNS (only for text that has Vietnamese letters, so plain English and numbers never touch a regex)
//   4. split on " · " (or " vs ") and translate each part (most concatenated labels are built that way)
//   5. ALL-CAPS text (e.g. "ĐỐI KHÁNG · MÀN 3"): translated in lower / sentence case and upper-cased again
// Anything not found is returned unchanged.

export const HAS_VI = /[àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ]/i;
const HAS_LETTER = /[A-Za-zÀ-ỹ]/;
const CACHE_MAX = 6000;
const SEPARATORS = [' · ', ' vs '];

export function makeTranslator(EN, PATTERNS) {
  const cache = new Map();
  let lowerIndex = null;

  const lower = (s) => s.toLocaleLowerCase('vi');
  const upper = (s) => s.toLocaleUpperCase('vi');

  function lowerLookup(s) {
    if (!lowerIndex) {
      lowerIndex = new Map();
      for (const [k, v] of EN) lowerIndex.set(lower(k), v);
    }
    return lowerIndex.get(s);
  }

  /** Translate trimmed text (no leading/trailing whitespace). Returns the same string when nothing applies. */
  function core(text, depth = 0) {
    if (depth > 6 || !text) return text;
    const hit = cache.get(text);
    if (hit !== undefined) return hit;
    const out = compute(text, depth);
    if (cache.size >= CACHE_MAX) cache.clear();
    cache.set(text, out);
    return out;
  }

  function compute(text, depth) {
    let v = EN.get(text);
    if (v !== undefined) return v;
    const flat = text.replace(/\s+/g, ' ');
    if (flat !== text) {
      v = EN.get(flat);
      if (v !== undefined) return v;
    }
    if (!HAS_VI.test(text)) return text;

    // "# comment" lines and "· fragment" pieces
    if (flat.startsWith('# ') || flat.startsWith('· ')) {
      const rest = core(flat.slice(2), depth + 1);
      if (rest !== flat.slice(2)) return flat.slice(0, 2) + rest;
    }

    const t = (x) => translate(x, depth + 1);
    for (let i = 0; i < PATTERNS.length; i++) {
      const m = PATTERNS[i][0].exec(flat);
      if (m) return PATTERNS[i][1](m, t);
    }

    for (const sep of SEPARATORS) {
      if (!flat.includes(sep)) continue;
      let changed = false;
      const parts = flat.split(sep).map((p) => {
        const r = core(p, depth + 1);
        if (r !== p) changed = true;
        return r;
      });
      if (changed) return parts.join(sep);
    }

    if (HAS_LETTER.test(flat) && flat === upper(flat)) {
      const lc = lower(flat);
      if (lc !== flat) {
        let r = lowerLookup(lc);
        if (r === undefined) {
          const cap = lc.charAt(0).toLocaleUpperCase('vi') + lc.slice(1);
          r = core(cap, depth + 1);
          if (r === cap) r = core(lc, depth + 1);
          if (r === cap || r === lc) r = undefined;
        }
        if (r !== undefined) return upper(r);
      }
    }
    return text;
  }

  /** Translate any string, keeping its leading/trailing whitespace. */
  function translate(str, depth = 0) {
    if (typeof str !== 'string' || !str) return str;
    const m = /^(\s*)([\s\S]*?)(\s*)$/.exec(str);
    if (!m[2]) return str;
    const out = core(m[2], depth);
    return out === m[2] ? str : m[1] + out + m[3];
  }

  return translate;
}
