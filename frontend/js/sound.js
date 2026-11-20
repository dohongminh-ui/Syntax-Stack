// WebAudio-synthesised sound effects + haptics. No audio files. One mute toggle covers both.
const KEY = 'syntaxstack.sound';
const muteListeners = new Set();
let ctx = null;
let master = null;
let muted = false;
try {
  muted = localStorage.getItem(KEY) === 'off';
} catch { /* storage blocked */ }

export const isMuted = () => muted;
export const onMuteChange = (listener) => { muteListeners.add(listener); };

export function setMuted(b) {
  muted = !!b;
  try {
    localStorage.setItem(KEY, muted ? 'off' : 'on');
  } catch { /* ignore */ }
  for (const listener of muteListeners) listener(muted);
}

function ensure() {
  if (!ctx) {
    const AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) return null;
    try {
      ctx = new AC();
      master = ctx.createGain();
      master.gain.value = 0.5;
      master.connect(ctx.destination);
    } catch {
      ctx = null;
      return null;
    }
  }
  if (ctx.state === 'suspended') ctx.resume().catch(() => {});
  return ctx;
}

export const prepareAudio = ensure;

// Autoplay policy: create / resume on the first user gesture.
for (const ev of ['pointerdown', 'keydown']) document.addEventListener(ev, ensure, { capture: true, passive: true });

export function haptic(pattern) {
  if (muted) return;
  // Browsers block (and log an error for) vibrate() before the first real tap on the page.
  if (navigator.userActivation && !navigator.userActivation.hasBeenActive) return;
  try {
    if (navigator.vibrate) navigator.vibrate(pattern);
  } catch { /* unsupported */ }
}

let noiseBuf = null;
function noise(c) {
  if (!noiseBuf) {
    noiseBuf = c.createBuffer(1, c.sampleRate, c.sampleRate);
    const d = noiseBuf.getChannelData(0);
    for (let i = 0; i < d.length; i++) d[i] = Math.random() * 2 - 1;
  }
  const s = c.createBufferSource();
  s.buffer = noiseBuf;
  return s;
}

/** Gain envelope: linear attack, exponential decay to silence. Returns the gain node. */
function env(c, t, peak, attack, dur) {
  const g = c.createGain();
  g.gain.setValueAtTime(0.0001, t);
  g.gain.linearRampToValueAtTime(peak, t + attack);
  g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
  g.connect(master);
  return g;
}

function noiseBurst(c, t, dur, peak, type, freq, sweepTo) {
  const n = noise(c);
  const f = c.createBiquadFilter();
  f.type = type;
  f.frequency.setValueAtTime(freq, t);
  if (sweepTo) f.frequency.exponentialRampToValueAtTime(sweepTo, t + dur);
  const g = env(c, t, peak, 0.002, dur);
  n.connect(f).connect(g);
  n.start(t, Math.random() * 0.5, dur + 0.02);
  n.stop(t + dur + 0.03);
}

function tone(c, t, type, freq, dur, peak, attack = 0.004, freqTo = null) {
  const o = c.createOscillator();
  o.type = type;
  o.frequency.setValueAtTime(freq, t);
  if (freqTo) o.frequency.exponentialRampToValueAtTime(freqTo, t + dur);
  const g = env(c, t, peak, attack, dur);
  o.connect(g);
  o.start(t);
  o.stop(t + dur + 0.02);
}

const hz = (semi) => 440 * Math.pow(2, semi / 12); // semitones from A4
const C5 = -9, E5 = -5, G5 = -2, B5 = 2, C6 = 3;

const D5 = -7, A5 = 0, D6 = 5, E6 = 7, G6 = 10;
const SCALE = [C5, D5, E5, G5, A5, C6, D6, E6];
let lastType = 0;

function chord(c, t, notes, peak, dur, shift = 0) {
  for (const n of notes) tone(c, t, 'triangle', hz(n + shift), dur, peak, 0.01);
}

function arpeggio(c, t, notes, peak, shift) {
  notes.forEach((n, i) => tone(c, t + i * 0.055, 'triangle', hz(n + shift), 0.16, peak, 0.006));
}

export function sfx(name, opts = {}) {
  if (muted) return;
  const c = ensure();
  if (!c || c.state === 'closed') return;
  const t = c.currentTime + 0.005;
  switch (name) {
    case 'pickup':
      noiseBurst(c, t, 0.015, 0.12, 'highpass', 3000);
      break;
    case 'drop': {
      const cells = Math.min(9, Math.max(1, opts.cells || 1));
      const peak = 0.45 + ((cells - 1) / 8) * 0.4;
      const k = 1 + (Math.random() * 0.08 - 0.04);
      noiseBurst(c, t, 0.04, peak, 'lowpass', 1200 * k);
      tone(c, t, 'sine', 140 * k, 0.07, peak, 0.002);
      haptic(8);
      break;
    }
    case 'lock':
      tone(c, t, 'triangle', hz(E5), 0.09, 0.3, 0.02);
      tone(c, t + 0.09, 'triangle', hz(B5), 0.09, 0.3, 0.02);
      haptic([10, 30, 10]);
      break;
    case 'clear': {
      const shift = Math.min(5, Math.max(0, (opts.streak || 1) - 1));
      arpeggio(c, t, [C5, E5, G5, C6], 0.26, shift);
      haptic([12, 40, 12]);
      break;
    }
    case 'crack':
      arpeggio(c, t, [C5, E5, G5], 0.14, 0);
      break;
    case 'wrong': {
      const lp = c.createBiquadFilter();
      lp.type = 'lowpass';
      lp.frequency.value = 900;
      lp.connect(master);
      for (const det of [0.99, 1.01]) {
        const o = c.createOscillator();
        o.type = 'square';
        o.frequency.setValueAtTime(220 * det, t);
        o.frequency.exponentialRampToValueAtTime(150 * det, t + 0.18);
        const g = c.createGain();
        g.gain.setValueAtTime(0.125, t);
        g.gain.exponentialRampToValueAtTime(0.0001, t + 0.2);
        o.connect(g).connect(lp);
        o.start(t);
        o.stop(t + 0.22);
      }
      haptic(30);
      break;
    }
    case 'bomb':
      noiseBurst(c, t, 0.25, 0.6, 'lowpass', 2000, 200);
      break;
    case 'nope':
      tone(c, t, 'sine', 110, 0.08, 0.2, 0.004);
      haptic(4);
      break;
    case 'click': {
      const k = 1 + (Math.random() * 0.08 - 0.04);
      noiseBurst(c, t, 0.03, 0.5, 'lowpass', 2200 * k);
      tone(c, t, 'sine', 180 * k, 0.05, 0.5, 0.002);
      haptic(6);
      break;
    }
    case 'enter':
      noiseBurst(c, t, 0.06, 0.8, 'lowpass', 900);
      tone(c, t, 'sine', 95, 0.11, 0.8, 0.003);
      haptic(10);
      break;
    case 'line': {
      const i = Math.min(SCALE.length - 1, Math.max(0, opts.i || 0));
      tone(c, t, 'triangle', hz(SCALE[i]), 0.07, 0.18, 0.004);
      break;
    }
    case 'compile':
      chord(c, t, [C5, E5, G5, C6], 0.12, 0.45);
      haptic([12, 40, 12]);
      break;
    case 'perfect':
      chord(c, t, [C5, E5, G5, C6], 0.12, 0.6, 5);
      break;
    case 'type': {
      const now = performance.now();
      if (now - lastType < 45) return;
      lastType = now;
      noiseBurst(c, t, 0.008, 0.05, 'highpass', 4000);
      break;
    }
    case 'star': {
      const i = Math.min(2, Math.max(0, opts.i || 0));
      tone(c, t, 'triangle', hz([E5, G5, C6][i]), 0.16, 0.25, 0.006);
      break;
    }
    case 'chime':
      tone(c, t, 'sine', hz(C6), 0.35, 0.2, 0.005);
      tone(c, t, 'sine', hz(G6), 0.35, 0.1, 0.005);
      break;
    case 'bzzt': {
      const lp = c.createBiquadFilter();
      lp.type = 'lowpass';
      lp.frequency.value = 600;
      lp.connect(master);
      const o = c.createOscillator();
      o.type = 'sawtooth';
      o.frequency.setValueAtTime(90, t);
      const g = c.createGain();
      g.gain.setValueAtTime(0.18, t);
      g.gain.exponentialRampToValueAtTime(0.0001, t + 0.16);
      o.connect(g).connect(lp);
      o.start(t);
      o.stop(t + 0.18);
      haptic(20);
      break;
    }
    case 'resolve':
      tone(c, t, 'triangle', hz(G5), 0.11, 0.2, 0.006);
      tone(c, t + 0.11, 'triangle', hz(C6), 0.11, 0.2, 0.006);
      break;
    // ---- Đối kháng (1v1) ----
    case 'send': // lines leave your board: a quick rising two-note whoosh
      tone(c, t, 'triangle', hz(G5), 0.09, 0.2, 0.004, hz(C6));
      tone(c, t + 0.07, 'triangle', hz(E6), 0.1, 0.16, 0.004);
      haptic(12);
      break;
    case 'incoming': // lines are queued against you: low double knock
      tone(c, t, 'square', 150, 0.08, 0.16, 0.004, 110);
      tone(c, t + 0.1, 'square', 130, 0.1, 0.16, 0.004, 90);
      haptic([20, 40, 20]);
      break;
    case 'land': // rows land from the bottom: a thud with a rumble
      noiseBurst(c, t, 0.22, 0.6, 'lowpass', 800, 120);
      tone(c, t, 'sine', 80, 0.2, 0.7, 0.002, 45);
      haptic([30, 30, 50]);
      break;
    case 'win':
      arpeggio(c, t, [C5, E5, G5, C6, E6], 0.24, 0);
      tone(c, t + 0.3, 'triangle', hz(G6), 0.5, 0.16, 0.01);
      haptic([15, 40, 15, 40, 30]);
      break;
    case 'lose':
      tone(c, t, 'triangle', hz(G5), 0.2, 0.22, 0.01, hz(E5));
      tone(c, t + 0.2, 'triangle', hz(E5), 0.22, 0.22, 0.01, hz(C5));
      tone(c, t + 0.42, 'triangle', hz(C5), 0.4, 0.2, 0.01, hz(-14));
      haptic(40);
      break;
    case 'tick':
      tone(c, t, 'sine', hz(G5), 0.1, 0.22, 0.004);
      break;
    case 'go':
      tone(c, t, 'triangle', hz(C6), 0.28, 0.26, 0.004);
      tone(c, t, 'triangle', hz(G6), 0.28, 0.14, 0.004);
      haptic(15);
      break;
    default:
  }
}
