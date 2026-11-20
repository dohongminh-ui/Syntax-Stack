// The stage of the "Chat with Misaki" screen: her Live2D model, or a fallback.
// Fallback chain: Live2D model -> portrait image (Save-Data, or no WebGL) -> the keycap avatar "M".
// The runtime (PixiJS, the unsafe-eval patch, Live2D Cubism Core, pixi-live2d-display) loads lazily, only when this
// stage is mounted AND frontend/live2d/misaki/misaki.model3.json exists. The model files are not committed
// (tools/setup_live2d.py creates them), so a fresh checkout simply shows the avatar.
import { el, reducedMotion } from './ui.js';
import { misakiAvatar } from './misaki.js';
import * as store from './storage.js';

const BASE = new URL('../live2d/misaki/', import.meta.url);
const MODEL_URL = new URL('misaki.model3.json', BASE).href;
const vendor = (file) => new URL('../vendor/' + file, import.meta.url).href;
// Live2D's official URL: the CSP allows exactly this file (backend/app/main.py). It is not vendored (Live2D's licence).
const CORE_URL = 'https://cubism.live2d.com/sdk-web/cubismcore/live2dcubismcore.min.js';

const THINKING_FACE = {
  ParamBrowLY: 0.35, ParamBrowRY: 0.08, ParamMouthForm: -0.12, ParamMouthOpenY: 0.52, key3: 1,
};
// Face sliders and effect toggles from the DeepSeek-chan rig. Motions only pose the arms.
const MOODS = {
  neutral: { face: {} },
  happy: { face: { ParamMouthForm: 0.45, EyeSmile: 0.25 }, motion: 'Raise' },
  excited: { face: { ParamMouthForm: 0.75, ParamMouthOpenY: 0.28, EyeSmile: 0.5 }, motion: 'Raise' },
  thinking: { face: THINKING_FACE, motion: 'Finger' },
  loading: { face: { ...THINKING_FACE, key8: 1 }, motion: 'Finger' },
  worried: { face: { BrowInnerUp: 0.3, ParamMouthForm: -0.25, key13: 1 } }, // sweat
  sad: { face: { BrowInnerUp: 0.45, ParamMouthForm: -0.4, key2: 1 } }, // tears
  shy: { face: { ParamMouthForm: 0.2, key5: 1 } }, // squeezed eyes
  dizzy: { face: { ParamMouthOpenY: 0.15, key3: 1 } }, // white circle eyes
};
const FACE_PARAMS = [...new Set(Object.values(MOODS).flatMap(({ face }) => Object.keys(face)))];
const ARM_PARAMS = {
  Raise: ['Movement2', 'Param59', 'Param60', 'Param61', 'Param62'],
  Finger: ['Movement3', 'Param36', 'Param39', 'Param40', 'Param41', 'Param42', 'Param43'],
};
const FACE_MS = 200;
const HOLD_MS = 2600; // how long the raised hand / pointing finger stays before the "back" clip plays

// Parts of the model the bundled Cubism framework cannot draw. They need per-drawable multiply/screen colours
// (Cubism 4.2+/5), which pixi-live2d-display 0.4.0 ignores, so they show up as a black keyhole between her eyes.
const HIDE_DRAWABLES = ['ArtMesh246', 'ArtMesh682'];

// Where the model sits, as fractions of the model's height (the canvas is 3749 x 7697 units).
// Tall form: the hair starts at ~0.10, the chest is at ~0.36, the waist at ~0.53; the head is centred at ~0.497 of the
// width and the hair and shoulders are ~0.56 of it wide. Desktop is waist-up, phone is head-to-chest.
// Chibi form (parameter Clothes2 = 1): the whole character spans ~0.11 to ~0.34 of the height and ~0.34 of the width,
// so it is framed whole. While the body type eases, the framing eases with it.
const FRAMING = {
  tall: { desktop: { from: 0.07, to: 0.52 }, phone: { from: 0.07, to: 0.31 }, wide: 0.56, cx: 0.497 },
  chibi: { desktop: { from: 0.085, to: 0.355 }, phone: { from: 0.095, to: 0.35 }, wide: 0.4, cx: 0.499 },
};
// Her eye line as a fraction of the model's height, per form (pointer follow aims from here).
const EYE_LINE = { tall: 0.205, chibi: 0.21 };
const BODY_PARAM = 'Clothes2'; // 0 tall, 0.4 a slightly smaller tall form, 1 chibi (checked by rendering all three)
const BODY_VALUE = { chibi: 1, normal: 0 };
const BODY_MS = 250;
const lerp = (a, b, t) => a + (b - a) * t;

let runtimePromise = null;

function loadScript(src, ms = 20000) {
  return new Promise((resolve, reject) => {
    const s = document.createElement('script');
    const timer = setTimeout(() => { s.remove(); reject(new Error('timeout ' + src)); }, ms);
    s.async = false;
    s.onload = () => { clearTimeout(timer); resolve(); };
    s.onerror = () => { clearTimeout(timer); s.remove(); reject(new Error('blocked or missing: ' + src)); };
    s.src = src;
    document.head.append(s);
  });
}

/** PixiJS 6 + the unsafe-eval patch (so the CSP needs no 'unsafe-eval') + Cubism Core + pixi-live2d-display. */
function loadRuntime() {
  if (!runtimePromise) {
    runtimePromise = (async () => {
      await loadScript(vendor('pixi-6.5.10.min.js'));
      await loadScript(vendor('pixi-unsafe-eval-6.5.10.min.js')); // must run before any renderer exists
      await loadScript(CORE_URL);
      await loadScript(vendor('pixi-live2d-display-0.4.0-cubism4.min.js'));
      if (!window.PIXI?.live2d?.Live2DModel) throw new Error('Live2D runtime did not start');
      return window.PIXI;
    })();
    runtimePromise.catch(() => { runtimePromise = null; });
  }
  return runtimePromise;
}

const hasWebGL = () => {
  try {
    const c = document.createElement('canvas');
    return !!(c.getContext('webgl2') || c.getContext('webgl'));
  } catch {
    return false;
  }
};
const saveData = () => !!navigator.connection?.saveData;

async function modelPresent() {
  try {
    const r = await fetch(MODEL_URL, { cache: 'no-cache' });
    if (!r.ok) return false;
    const j = await r.json();
    return !!j?.FileReferences?.Moc;
  } catch {
    return false;
  }
}

function portraitUrl() {
  const probe = document.createElement('canvas');
  const webp = probe.toDataURL?.('image/webp').startsWith('data:image/webp');
  return new URL(webp ? 'portrait.webp' : 'portrait.png', BASE).href;
}

/**
 * Builds the stage inside `host` (the host should have position: relative and a size). Returns
 * `{ ready, setMood, pause, resume, refit, mode }`. `mode` is 'avatar' | 'portrait' | 'model' and changes as things load.
 */
export function mountStage(host, { isPhone = () => innerWidth < 900, bodySwitch = null } = {}) {
  const avatar = el('div', { class: 'mk-fallback' }, misakiAvatar({ cls: 'mk-avatar-big' }));
  host.replaceChildren(avatar);
  host.dataset.state = 'avatar';

  const api = {
    mode: 'avatar',
    ready: Promise.resolve('avatar'),
    setMood() {},
    pause() {},
    resume() {},
    refit() {},
  };
  let mood = 'neutral';
  let live = null; // set once the model is up
  api.setMood = (m) => {
    mood = Object.hasOwn(MOODS, m) ? m : 'neutral';
    live?.apply(mood);
  };
  const set = (mode) => {
    api.mode = mode;
    host.dataset.state = mode;
  };

  const showPortrait = () => new Promise((resolve) => {
    const img = el('img', { class: 'mk-portrait', alt: '', decoding: 'async', draggable: 'false' });
    img.addEventListener('load', () => {
      host.append(img);
      set('portrait');
      resolve('portrait');
    }, { once: true });
    img.addEventListener('error', () => resolve('avatar'), { once: true });
    img.src = portraitUrl();
  });

  api.ready = (async () => {
    if (!(await modelPresent())) return 'avatar';
    if (saveData() || !hasWebGL()) return showPortrait();
    try {
      const PIXI = await loadRuntime();
      live = await buildModel(PIXI, host, isPhone, () => mood, bodySwitch);
    } catch (e) {
      console.warn('Misaki Live2D model unavailable:', e.message);
      return showPortrait();
    }
    set('model');
    live.apply(mood);
    Object.assign(api, {
      pause: () => live.pause(),
      resume: () => live.resume(),
      refit: () => live.fit(),
    });
    return 'model';
  })();
  return api;
}

async function buildModel(PIXI, host, isPhone, getMood, bodySwitch) {
  const { Live2DModel, MotionPriority } = PIXI.live2d;
  const canvas = el('canvas', { class: 'mk-canvas' });
  const rect = host.getBoundingClientRect();
  const app = new PIXI.Application({
    view: canvas,
    width: Math.max(1, Math.round(rect.width)),
    height: Math.max(1, Math.round(rect.height)),
    backgroundAlpha: 0,
    antialias: true,
    autoDensity: true,
    resolution: Math.min(window.devicePixelRatio || 1, 2),
    powerPreference: 'low-power',
    sharedTicker: true,
    autoStart: true,
  });
  let model;
  try {
    model = await Live2DModel.from(MODEL_URL, { autoInteract: false });
  } catch (e) {
    app.destroy(true);
    throw e;
  }
  host.append(canvas);
  app.stage.addChild(model);
  const im = model.internalModel;

  // hide the parts the old framework draws wrongly (see HIDE_DRAWABLES)
  const drawables = im.coreModel._model?.drawables;
  const hide = drawables ? HIDE_DRAWABLES.map((id) => Array.from(drawables.ids).indexOf(id)).filter((i) => i >= 0) : [];
  if (hide.length) {
    const update = im.update.bind(im);
    im.update = (dt, now) => {
      update(dt, now);
      for (const i of hide) drawables.opacities[i] = 0;
    };
  }

  const baseW = model.width;
  const baseH = model.height;

  // body type: Clothes2 is written on every frame, after motions and expressions, so it always wins; it eases over 250 ms
  const first = BODY_VALUE[store.loadMisakiBody()];
  const body = { value: first, from: first, target: first, t0: 0 };
  const place = () => {
    const r = host.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) return;
    const t = body.value; // 0 tall .. 1 chibi
    const k = isPhone() ? 'phone' : 'desktop';
    const A = FRAMING.tall;
    const B = FRAMING.chibi;
    const from = lerp(A[k].from, B[k].from, t);
    const to = lerp(A[k].to, B[k].to, t);
    const wide = lerp(A.wide, B.wide, t);
    // as large as the crop allows, but the hair and shoulders may not be wider than the stage
    const s = Math.min(r.height / ((to - from) * baseH), (r.width * 1.04) / (wide * baseW));
    const cropH = (to - from) * baseH * s;
    model.scale.set(s);
    model.x = r.width / 2 - baseW * s * lerp(A.cx, B.cx, t);
    // the chibi is shown whole: centre it vertically when the width is what limits the size
    model.y = -from * baseH * s + (t > 0.5 ? Math.max(0, (r.height - cropH) / 2) : 0);
  };
  const fit = () => {
    const r = host.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) return;
    app.renderer.resize(Math.round(r.width), Math.round(r.height));
    place();
  };
  fit();
  const ro = new ResizeObserver(fit);
  ro.observe(host);
  host.dataset.body = body.target ? 'chibi' : 'normal';

  // Head, body and breathing. This rig does not take ParamAngleX/ParamBodyAngleX directly: its physics reads its own
  // tracking inputs (AngleX/Y/Z, PositionX/Y/Z, ParamBreath, all -30..30 except breath 0..1) and writes the Param*
  // angles, so anything set on those is overwritten. Feed the inputs instead, before physics runs (afterMotionUpdate),
  // from the smoothed gaze target plus a slow idle sway. The library's own breath swings ParamBreath -0.5..0.5, half
  // of it clipped at 0, so it is replaced by a full 0..1 cycle.
  im.breath?.setParameters?.([]);
  const core = im.coreModel;
  const motionManager = im.motionManager;
  const sliders = FACE_PARAMS.map((id) => ({ id, index: core.getParameterIndex(id), from: 0, value: 0 }));
  const arms = Object.entries(ARM_PARAMS).map(([name, ids]) => [name, ids.map((id) => core.getParameterIndex(id))]);
  let face = MOODS.neutral.face;
  let faceStarted = 0;
  let gesture = null; // owns one arm switch through its hold and return clip
  let holdTimer = 0;
  let returning = false;
  motionManager.on('motionStart', (name) => { returning = name === `${gesture}Back`; });
  motionManager.on('motionFinish', () => {
    if (returning) gesture = null;
    returning = false;
  });
  im.on('afterMotionUpdate', () => {
    const now = performance.now();
    const t = now / 1000;
    const calm = reducedMotion() ? 0 : 1; // reduced motion: breathing only, no sway
    // Cubism saves motion parameters here. Restore the unused arm's switch and joint angles together.
    for (const [name, indices] of arms) {
      if (calm && gesture === name) continue;
      for (const index of indices) core.setParameterValueByIndex(index, 0);
    }
    // Set the face before physics so the eye, brow and cheek deformers respond to the sliders.
    const progress = calm ? Math.min(1, (now - faceStarted) / FACE_MS) : 1;
    const blend = 1 - (1 - progress) ** 3;
    for (const slider of sliders) {
      slider.value = lerp(slider.from, face[slider.id] ?? 0, blend);
      core.setParameterValueByIndex(slider.index, slider.value);
    }
    const fc = im.focusController;
    // belt and braces: never let a bad gaze value lock the pose (see the pointer handler)
    if (![fc.x, fc.y, fc.vx, fc.vy, fc.targetX, fc.targetY].every(Number.isFinite)) {
      Object.assign(fc, { x: 0, y: 0, vx: 0, vy: 0, targetX: 0, targetY: 0 });
    }
    const fx = fc.x;
    const fy = fc.y;
    const sway = (period, amp, phase = 0) => calm * amp * Math.sin((t / period + phase) * Math.PI * 2);
    core.setParameterValueById('AngleX', fx * 24 + sway(6.5, 3));
    core.setParameterValueById('AngleY', fy * 18 + sway(4.7, 2, 0.3));
    core.setParameterValueById('AngleZ', -fx * fy * 14 + sway(5.6, 3, 0.6));
    core.setParameterValueById('PositionX', fx * 9 + sway(8.3, 2, 0.2));
    core.setParameterValueById('PositionY', fy * 5);
    core.setParameterValueById('PositionZ', -fx * fy * 8 + sway(7.1, 2, 0.5));
    core.setParameterValueById('ParamBreath', 0.5 + 0.5 * Math.sin((t / 3.4) * Math.PI * 2));
  });

  im.on('beforeModelUpdate', () => {
    if (body.value !== body.target) {
      const t = Math.min(1, (performance.now() - body.t0) / BODY_MS);
      body.value = t >= 1 ? body.target : lerp(body.from, body.target, 1 - (1 - t) ** 3);
      place();
    }
    im.coreModel.setParameterValueById(BODY_PARAM, body.value);
  });
  const setBody = (name) => {
    if (!(name in BODY_VALUE)) return;
    body.from = body.value;
    body.target = BODY_VALUE[name];
    body.t0 = performance.now();
    if (reducedMotion()) body.value = body.target;
    host.dataset.body = name;
    store.saveMisakiBody(name);
    place();
  };
  if (bodySwitch) {
    const name = body.target ? 'chibi' : 'normal';
    for (const r of bodySwitch.querySelectorAll('input[type=radio]')) {
      r.checked = r.value === name;
      r.addEventListener('change', () => r.checked && setBody(r.value));
    }
    bodySwitch.hidden = false; // only a loaded model has a body to change
  }

  // pointer follow: desktop (mouse) only, and not under reduced motion
  const follow = matchMedia('(hover: hover) and (pointer: fine)');
  let pending = null;
  const onMove = (e) => {
    if (reducedMotion() || !follow.matches || e.pointerType === 'touch') return;
    if (pending) return;
    pending = requestAnimationFrame(() => {
      pending = null;
      // Not model.focus(): it aims from the centre of the whole 3749 x 7697 canvas (her legs) and snaps to full
      // deflection. Aim from her eye line instead and scale with distance, so she glances rather than rolls her eyes.
      const r = canvas.getBoundingClientRect();
      // Screen closed or panel hidden: the canvas is 0 x 0 and the maths below would divide by zero. A NaN target
      // never recovers (the smoothing keeps it NaN) and freezes her head in place when the chat is reopened.
      if (r.width < 2 || r.height < 2) return;
      const s = model.scale.x; // same model units as place()
      const eye = { x: model.x + baseW * s * lerp(FRAMING.tall.cx, FRAMING.chibi.cx, body.value),
        y: model.y + baseH * s * lerp(EYE_LINE.tall, EYE_LINE.chibi, body.value) };
      const reach = Math.max(r.width, r.height) * 0.75;
      let dx = (e.clientX - r.left - eye.x) / reach;
      let dy = (e.clientY - r.top - eye.y) / reach;
      const len = Math.hypot(dx, dy);
      if (len > 1) { dx /= len; dy /= len; }
      im.focusController.focus(dx, -dy);
    });
  };
  window.addEventListener('pointermove', onMove, { passive: true });
  document.documentElement.addEventListener('mouseleave', () => im.focusController.focus(0, 0));

  const stopGesture = () => {
    if (gesture) motionManager.stopAllMotions();
    gesture = null;
    returning = false;
  };
  const release = () => {
    clearTimeout(holdTimer);
    holdTimer = 0;
    if (!gesture) return;
    const [armSwitch] = ARM_PARAMS[gesture];
    // A return clip starts in the raised pose. Skip it if a fast reply arrived before the arm switched.
    if (core.getParameterValueById(armSwitch) < 0.5) {
      stopGesture();
      return;
    }
    model.motion(`${gesture}Back`, 0, MotionPriority.FORCE).catch(() => {});
  };

  const apply = (name) => {
    const m = MOODS[name] || MOODS.neutral;
    if (face !== m.face) {
      for (const slider of sliders) slider.from = slider.value;
      face = m.face;
      faceStarted = performance.now();
    }
    if (reducedMotion()) {
      clearTimeout(holdTimer);
      holdTimer = 0;
      stopGesture();
      return;
    }
    if (!m.motion) {
      if (holdTimer) release();
      return;
    }
    if (gesture !== m.motion || !holdTimer) {
      // Stop the old clip or reservation before a new gesture takes over the shared rig.
      stopGesture();
      gesture = m.motion;
      model.motion(gesture, 0, MotionPriority.FORCE).catch(() => {});
    }
    clearTimeout(holdTimer);
    holdTimer = setTimeout(release, HOLD_MS);
  };

  return {
    apply,
    fit,
    pause() { PIXI.Ticker.shared.stop(); },
    resume() { PIXI.Ticker.shared.start(); fit(); apply(getMood()); },
  };
}
