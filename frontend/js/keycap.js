// The keycap: one reusable component. Pure CSS lives in base.css (.key / .cap-top / .legend).
// Structure: .key (skirt) > .cap-top (cap face) > .legend
import { icon } from './icons.js';

/**
 * @param {object} o
 * @param {string} [o.tag='span']       'button' for interactive keys
 * @param {string} [o.topic='neutral']  variables | conditions | loops | functions | neutral | bug
 * @param {string|Node} [o.legend]      text or node placed on the cap
 * @param {string} [o.legendClass]      'legend' (top-left, default) | 'kb-label' (inline label) | 'legend legend-c'
 * @param {number} [o.u]                width in units (rows tokens)
 * @param {boolean} [o.enter]           adds the bottom-right enter glyph
 * @param {string} [o.cls]              extra classes on the key
 */
export function keycap({ tag = 'span', topic = 'neutral', legend = '', legendClass = 'legend', u = null, enter = false, cls = '', variant = '' } = {}) {
  const key = document.createElement(tag);
  key.className = ['key', 't-' + topic, variant === 'btn' ? 'key-btn' : '', enter ? 'enter-key' : '', u ? 'u-' + u : '', cls].filter(Boolean).join(' ');
  const top = document.createElement('span');
  top.className = 'cap-top';
  const lg = document.createElement('span');
  lg.className = legendClass;
  if (legend && legend.nodeType) lg.append(legend);
  else lg.textContent = legend;
  top.append(lg);
  if (enter) {
    const r = document.createElement('span');
    r.className = 'ret';
    r.setAttribute('aria-hidden', 'true');
    r.append(icon('enter', { size: 14 }));
    top.append(r);
  }
  key.append(top);
  return key;
}

/** Replace the legend text of an existing key without touching its structure. */
export function setLegend(key, text) {
  const l = key.querySelector('.legend, .kb-label');
  if (l && l.textContent !== text) l.textContent = text;
}

export const TOPIC_CLASS = { variables: 't-variables', conditions: 't-conditions', loops: 't-loops', functions: 't-functions', syntax: 't-neutral', neutral: 't-neutral', bug: 't-bug' };
