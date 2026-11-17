// The indicator strip (header): wordmark, mode label, streak, BUILD/WARN/CRASH LEDs, score.
import { icon } from './icons.js';
import { rollNumber, reducedMotion } from './ui.js';
import { isMuted, setMuted, sfx } from './sound.js';

const $ = (id) => document.getElementById(id);
let backFn = null;
let status = null;

export function initStrip() {
  const back = $('strip-back');
  back.append(icon('chevron-left', { size: 22 }));
  back.addEventListener('click', () => backFn && backFn());
  const snd = $('strip-sound');
  const paint = () => {
    const m = isMuted();
    snd.replaceChildren(icon(m ? 'volume-x' : 'volume', { size: 20 }));
    snd.setAttribute('aria-pressed', m ? 'true' : 'false');
    snd.setAttribute('aria-label', m ? 'Bật âm thanh' : 'Tắt âm thanh');
  };
  paint();
  snd.addEventListener('click', () => {
    setMuted(!isMuted());
    paint();
    if (!isMuted()) sfx('drop', { cells: 2 });
  });
}

export function showStrip(on, { back = null, backLabel = 'Quay lại' } = {}) {
  $('strip').hidden = !on;
  backFn = back;
  const b = $('strip-back');
  b.hidden = !back;
  b.setAttribute('aria-label', backLabel);
}

export function setMode(text) {
  $('strip-mode').textContent = text;
}

export function setScore(n, { roll = true } = {}) {
  const node = $('hud-score');
  if (roll) rollNumber(node, n, 400);
  else {
    node.dataset.v = String(n);
    node.textContent = n;
  }
}

export function setStreak(n) {
  const s = $('strip-streak');
  if (n == null) {
    s.hidden = true;
    return;
  }
  s.hidden = false;
  s.classList.toggle('hot', n >= 2);
  s.textContent = '';
  s.append(icon('flame', { size: 18 }), `×${n}`);
  s.setAttribute('aria-label', `Streak Clean Build ${n}`);
}

const LED_MODES = {
  rescue: { labels: ['BUILD', 'WARN', 'CRASH'], colors: ['var(--ok)', 'var(--warn)', 'var(--crash)'], index: { ok: 0, warn: 1, crash: 2 },
    aria: { ok: 'Trạng thái: ổn định', warn: 'Trạng thái: cảnh báo', crash: 'Trạng thái: crash' } },
  // Syntax Rows: nothing lit while idle, RUN while a run is in flight, then FAIL or PASS.
  rows: { labels: ['RUN', 'FAIL', 'PASS'], colors: ['var(--warn)', 'var(--crash)', 'var(--ok)'], index: { run: 0, fail: 1, pass: 2 },
    aria: { run: 'Đang chạy kiểm tra', fail: 'Lần chạy gần nhất: chưa đạt', pass: 'Lần chạy gần nhất: đạt' } },
};
let ledMode = 'rescue';

export function setLedMode(mode) {
  ledMode = mode;
  const cfg = LED_MODES[mode];
  document.querySelectorAll('#strip-leds .led-item').forEach((item, i) => {
    const led = item.querySelector('.led');
    led.style.setProperty('--c', cfg.colors[i]);
    led.classList.remove('on', 'blink');
    item.querySelector('.led-l').textContent = cfg.labels[i];
  });
  status = null;
}

/** rescue: 'ok' | 'warn' | 'crash'. rows: 'run' | 'fail' | 'pass' | null (none lit). The lit LED blinks when it changes. */
export function setStatus(next, { blink = true } = {}) {
  const cfg = LED_MODES[ledMode];
  const lit = next == null ? -1 : cfg.index[next];
  document.querySelectorAll('#strip-leds .led').forEach((led, i) => {
    const on = i === lit;
    led.classList.toggle('on', on);
    if (on && next !== status && blink && !reducedMotion()) {
      led.classList.remove('blink');
      void led.offsetWidth;
      led.classList.add('blink');
    }
  });
  $('strip-leds').setAttribute('aria-label', next == null ? 'Chưa chạy kiểm tra' : cfg.aria[next]);
  status = next;
}
