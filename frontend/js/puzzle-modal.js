// Puzzle panel (editor window): renders the four puzzle types, hints, commit/confirm and result.
// Desktop: docks over the side column so the board stays visible. Phone: bottom sheet with a grab handle.
import * as api from './api.js';
import { recordMistake } from './storage.js';
import { HINT_PENALTY_PCT } from './game.js';
import { el, anim, EASE, reducedMotion } from './ui.js';
import { icon } from './icons.js';
import { keycap } from './keycap.js';
import { highlightPy } from './highlight.js';
import { FILE_NAMES, titleBar, codeBlock, terminal, diffView, comment, tutorNote } from './editor.js';

const TYPE_LABEL = {
  fill_blank: 'Điền chỗ trống',
  predict_output: 'Đoán đầu ra',
  parsons: 'Sắp xếp mã',
  find_bug: 'Tìm bug',
};
const desktop = () => window.matchMedia('(min-width: 1024px)').matches;

function enterKey(label, onclick, { id, disabled = false, cls = '' } = {}) {
  const k = keycap({ tag: 'button', topic: 'neutral', legend: label, legendClass: 'kb-label', variant: 'btn', enter: true, cls });
  k.type = 'button';
  if (id) k.id = id;
  k.disabled = disabled;
  k.addEventListener('click', onclick);
  return k;
}

/**
 * opts: {puzzle, topic, title, boss, tag, maxAttempts, free, penalties, awardText, startHint}
 * returns Promise<{correct, maxHint, response}>
 */
export function openPuzzle(opts) {
  const { puzzle, topic, title, boss = null, tag = null, maxAttempts = 1, free = 0, penalties = true,
    awardText, startHint = 0, onResult = null, standalone = false, intro = '', introSource = 'canned', closeLabel = 'Về báo cáo' } = opts;
  const root = document.getElementById('modal-root');
  const app = document.getElementById('app');
  const gameScreen = document.getElementById('screen-game');

  return new Promise((resolve) => {
    const st = {
      option: null,
      lineId: null,
      order: puzzle.type === 'parsons' ? puzzle.lines.map((l) => ({ id: l.id, indent: 0 })) : [],
      active: puzzle.type === 'parsons' ? puzzle.lines[0].id : null,
      hints: [],
      attempts: 0,
      phase: 'answer', // answer | confirm | sending | result
      error: '',
      note: '',
      primary: null,
    };
    const maxHint = () => Math.max(startHint, st.hints.length);
    const lineById = (id) => puzzle.lines.find((l) => l.id === id);
    // find_bug options carry `line_id`. If a server build omits it, infer the target line from shared words (best effort).
    const words = (t) => new Set(t.match(/[\wÀ-ỹ]+/g) || []);
    const guessed = new Map();
    const optLine = (o) => {
      if (o.line_id) return o.line_id;
      if (guessed.has(o.id)) return guessed.get(o.id);
      const w = words(o.text);
      let best = null;
      let bestScore = 0;
      for (const l of puzzle.lines) {
        const lw = words(l.text);
        let sc = [...w].filter((x) => lw.has(x)).length;
        if ((o.text.match(/^\w+/) || [''])[0] === (l.text.match(/^\w+/) || ['x'])[0]) sc += 1.5;
        if (sc > bestScore) {
          bestScore = sc;
          best = l.id;
        }
      }
      guessed.set(o.id, best);
      return best;
    };

    const titleId = 'pz-title';
    const meta = boss ? boss.toUpperCase() : tag ? tag : `tier ${puzzle.tier}/3`;
    const barHolder = el('div');
    const body = el('div', { class: 'pz-body' });
    const edge = el('div', { class: 'pz-edge', 'aria-hidden': 'true' });
    const panel = el('div', { class: 'pz-panel editor', role: 'dialog', 'aria-modal': 'true', 'aria-labelledby': titleId, tabindex: '-1' },
      el('div', { class: 'pz-grab', 'aria-hidden': 'true' }, el('i')), barHolder, body, edge);
    const scrim = el('div', { class: 'pz-scrim' });
    const layer = el('div', { class: 'pz-layer t-' + topic + (standalone ? ' standalone' : '') }, scrim, panel);

    panel.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        if (standalone && st.phase !== 'sending') finish();
      }
      if (e.key === 'Enter' && !e.target.closest('button, input, a') && st.primary) {
        e.preventDefault();
        st.primary();
      }
    });

    // ---- docking ----
    function dock() {
      if (standalone) return;
      const side = document.querySelector('#screen-game .side');
      if (!side || !desktop()) return;
      const r = side.getBoundingClientRect();
      layer.style.setProperty('--dock-x', r.left + 'px');
      layer.style.setProperty('--dock-y', Math.max(r.top, 64) + 'px');
      layer.style.setProperty('--dock-w', r.width + 'px');
    }
    window.addEventListener('resize', dock);

    // ---- answer widgets ----
    function correctOptionId() {
      if (st.phase !== 'result') return null;
      if (st.correct) return st.option;
      const sol = st.response?.solution_code;
      if (!sol || !puzzle.options) return null;
      const norm = (t) => t.split('\n').map((x) => x.replace(/\s+$/, '')).join('\n').trim();
      const S = norm(sol);
      for (const o of puzzle.options) {
        let cand;
        if (puzzle.type === 'fill_blank') cand = puzzle.code.replace('___', o.text);
        else if (puzzle.type === 'predict_output') cand = o.text;
        else cand = puzzle.lines.map((l) => '    '.repeat(l.indent) + (l.id === optLine(o) ? o.text : l.text)).join('\n');
        const target = puzzle.type === 'predict_output' ? S.replace(/^Đầu ra:\s*/i, '') : S;
        if (norm(cand) === target) return o.id;
      }
      return null;
    }

    function optionKeys(list = puzzle.options, find = false) {
      const block = puzzle.type === 'predict_output' || find;
      const grp = el('div', { class: 'opts' + (block ? ' opts-block' : ''), role: 'radiogroup', 'aria-label': 'Lựa chọn' });
      const result = st.phase === 'result';
      const rightId = correctOptionId();
      for (const o of list) {
        const sel = st.option === o.id;
        let legend;
        if (find) {
          const n = puzzle.lines.findIndex((l) => l.id === optLine(o)) + 1;
          legend = el('span', { class: 'opt-fl' }, n ? el('span', { class: 'opt-line', text: `dòng ${n}` }) : null, el('pre', { class: 'opt-code', text: o.text }));
        } else legend = el('pre', { class: 'opt-text', text: o.text });
        let state = '';
        if (result) {
          if (o.id === rightId || (sel && st.correct)) state = ' is-correct';
          else if (sel) state = ' is-wrong';
        }
        const k = keycap({ tag: 'button', topic: 'neutral', legend, legendClass: 'kb-label', variant: 'btn', cls: 'opt' + (find ? ' opt-find' : '') + (sel ? ' sel' : '') + state });
        k.type = 'button';
        k.setAttribute('role', 'radio');
        k.setAttribute('aria-checked', sel ? 'true' : 'false');
        k.disabled = st.phase !== 'answer';
        k.addEventListener('click', () => {
          st.option = o.id;
          render();
          body.querySelector('.opt.sel')?.focus({ preventScroll: true });
        });
        grp.append(k);
      }
      return grp;
    }

    function smallKey(iconName, aria, fn, off) {
      const k = keycap({ tag: 'button', topic: 'neutral', legend: icon(iconName, { size: 18 }), legendClass: 'legend legend-c', cls: 'sk' });
      k.type = 'button';
      k.disabled = off;
      k.setAttribute('aria-label', aria);
      k.addEventListener('click', fn);
      return k;
    }

    function parsonsWidget() {
      const list = el('ul', { class: 'pl', 'aria-label': 'Các dòng mã, sắp xếp từ trên xuống' });
      st.order.forEach((it, i) => {
        const line = lineById(it.id);
        const dis = st.phase !== 'answer';
        const grip = el('span', { class: 'grip', 'aria-hidden': 'true', onpointerdown: (e) => startDrag(e, li) }, icon('grip', { size: 18 }));
        const lineKey = keycap({ tag: 'button', topic: 'neutral', legend: '', legendClass: 'pl-text', cls: 'pline' });
        lineKey.type = 'button';
        lineKey.disabled = dis;
        const lt = lineKey.querySelector('.pl-text');
        lt.append(el('code', { class: 'pc-code', text: line.text }));
        if (it.indent) lt.append(el('span', { class: 'pc-ind', text: `⇥${it.indent}`, 'aria-label': `thụt ${it.indent} cấp` }));
        lineKey.querySelector('.cap-top').prepend(grip);
        lineKey.addEventListener('click', () => { st.active = it.id; render(); });
        lineKey.setAttribute('aria-label', `Dòng ${i + 1}: ${line.text}, thụt lề ${it.indent}`);
        const ctl = el('div', { class: 'pc-ctl', role: 'group', 'aria-label': 'Điều khiển dòng ' + line.text },
          smallKey('indent-out', `Giảm thụt lề dòng ${line.text}`, () => { it.indent = Math.max(0, it.indent - 1); render(); }, dis || it.indent === 0),
          smallKey('indent-in', `Tăng thụt lề dòng ${line.text}`, () => { it.indent = Math.min(2, it.indent + 1); render(); }, dis || it.indent === 2),
          smallKey('arrow-up', `Đưa dòng ${line.text} lên`, () => move(i, -1), dis || i === 0),
          smallKey('arrow-down', `Đưa dòng ${line.text} xuống`, () => move(i, 1), dis || i === st.order.length - 1));
        const li = el('li', { class: 'pcard' + (st.active === it.id ? ' active' : ''), dataset: { id: it.id }, style: { '--ind': it.indent } }, lineKey, st.active === it.id ? ctl : null);
        list.append(li);
      });
      const preview = el('div', { class: 'pv' }, comment('Xem trước chương trình', 'pv-label'),
        codeBlock(st.order.map((it) => '    '.repeat(it.indent) + lineById(it.id).text)));
      return el('div', { class: 'parsons' }, list, preview);
    }
    function move(i, d) {
      const j = i + d;
      if (j < 0 || j >= st.order.length) return;
      [st.order[i], st.order[j]] = [st.order[j], st.order[i]];
      render();
    }
    function startDrag(e, li) {
      if (st.phase !== 'answer') return;
      e.preventDefault();
      const list = li.parentElement;
      li.classList.add('dragging');
      const onMove = (ev) => {
        const sibs = [...list.children].filter((x) => x !== li);
        const next = sibs.find((x) => {
          const r = x.getBoundingClientRect();
          return ev.clientY < r.top + r.height / 2;
        });
        if (next) list.insertBefore(li, next);
        else list.append(li);
      };
      const onUp = () => {
        window.removeEventListener('pointermove', onMove);
        window.removeEventListener('pointerup', onUp);
        window.removeEventListener('pointercancel', onUp);
        const ids = [...list.children].map((x) => x.dataset.id);
        st.order = ids.map((id) => st.order.find((o) => o.id === id));
        st.active = li.dataset.id;
        render();
      };
      window.addEventListener('pointermove', onMove);
      window.addEventListener('pointerup', onUp);
      window.addEventListener('pointercancel', onUp);
    }

    function findBugWidget() {
      const selOpt = puzzle.options.find((o) => o.id === st.option);
      const hi = st.lineId || (selOpt && optLine(selOpt));
      const code = el('div', { class: 'code code-pick', role: 'listbox', 'aria-label': 'Chạm vào một dòng để chỉ xem các cách sửa của dòng đó' });
      puzzle.lines.forEach((l, i) => {
        const lt = el('span', { class: 'lt' });
        lt.append(document.createTextNode('    '.repeat(l.indent)));
        lt.append(highlightPy(l.text));
        code.append(
          el('button', {
            class: 'code-line pick' + (hi === l.id ? ' target' : ''), type: 'button', role: 'option', 'aria-selected': st.lineId === l.id ? 'true' : 'false',
            disabled: st.phase !== 'answer',
            onclick: () => { st.lineId = st.lineId === l.id ? null : l.id; render(); },
          }, el('span', { class: 'ln', 'aria-hidden': 'true', text: i + 1 }), lt),
        );
      });
      let list = puzzle.options;
      let head = 'Chọn cách sửa đúng. Chạm vào một dòng để lọc các lựa chọn.';
      if (st.lineId) {
        const filtered = puzzle.options.filter((o) => optLine(o) === st.lineId || o.id === st.option);
        if (filtered.length) {
          list = filtered;
          head = `Các cách sửa dòng ${puzzle.lines.findIndex((l) => l.id === st.lineId) + 1}:`;
        } else head = 'Không có lựa chọn cho dòng này. Đang hiện tất cả:';
      }
      const wrap = el('div', { class: 'fb' }, code);
      wrap.append(el('div', { class: 'fb-filter' }, comment(head, 'sub'),
        st.lineId ? el('button', { class: 'btn', type: 'button', text: 'Xem tất cả', onclick: () => { st.lineId = null; render(); } }) : null));
      wrap.append(optionKeys(list, true));
      return wrap;
    }

    // ---- hints ----
    function penaltyText(level) {
      if (!penalties) return 'không ảnh hưởng điểm';
      if (level <= free) return 'miễn phí';
      return `−${HINT_PENALTY_PCT[level]}% điểm`;
    }
    async function showHint() {
      const level = st.hints.length + 1;
      if (level > 3 || st.phase !== 'answer') return;
      st.note = '';
      try {
        const h = await api.getHint(puzzle.id, level);
        st.hints.push(h.text);
      } catch (e) {
        st.note = 'Không tải được gợi ý: ' + e.message;
      }
      render();
    }

    // ---- submit ----
    function payload(reveal) {
      if (puzzle.type === 'parsons') return { order: st.order.map((o) => ({ line_id: o.id, indent: o.indent })), reveal };
      if (puzzle.type === 'find_bug') {
        // v2 answers with option_id only; line_id is ignored by the server but kept for older builds
        const o = puzzle.options.find((x) => x.id === st.option);
        return { option_id: st.option, line_id: o ? optLine(o) : undefined, reveal };
      }
      return { option_id: st.option, reveal };
    }
    const complete = () => (puzzle.type === 'parsons' ? true : !!st.option);

    async function submit() {
      st.attempts++;
      const final = st.attempts >= maxAttempts;
      st.phase = 'sending';
      st.error = '';
      render();
      let res;
      const answer = payload(final);
      try {
        res = await api.submitAnswer(puzzle.id, answer);
      } catch (e) {
        st.attempts--;
        st.phase = 'answer';
        st.error = 'Không gửi được câu trả lời: ' + e.message + '. Hãy thử lại.';
        render();
        return;
      }
      if (!res.correct) {
        st.wrongAnswer = answer;
        if (!standalone && !api.isMock) recordMistake({ topic, puzzleId: puzzle.id });
      }
      if (res.correct || final) {
        st.phase = 'result';
        st.response = res;
        st.correct = res.correct;
        render();
        flashEdge(res.correct);
        if (onResult) onResult(res);
        body.querySelector('#pz-continue')?.focus({ preventScroll: true });
        body.querySelector('.res')?.scrollIntoView({ block: 'nearest' });
      } else {
        st.phase = 'answer';
        st.error = res.message || 'Chưa đúng.';
        render();
        anim(panel, [0, -5, 5, -4, 4, 0].map((x) => ({ transform: `translateX(${x}px)` })), { duration: 260, easing: EASE.out });
      }
    }

    function flashEdge(ok) {
      edge.style.borderColor = ok ? 'var(--matcha)' : 'var(--crash)';
      anim(edge, [{ opacity: 0 }, { opacity: 1, offset: 0.25 }, { opacity: 0 }], { duration: 520, easing: EASE.out });
    }

    function finish() {
      if (st.closing) return;
      st.closing = true;
      window.removeEventListener('resize', dock);
      layer.style.pointerEvents = 'none';
      panel.style.pointerEvents = 'none';
      app.inert = false;
      gameScreen.classList.remove('dim');
      document.body.classList.remove('modal-open');
      // resolve immediately so the next animation (clear / crash) starts the moment "Tiếp tục" is pressed
      resolve({ correct: !!st.correct, maxHint: maxHint(), response: st.response, answer: st.wrongAnswer || null });
      const out = desktop() ? [{ transform: 'none', opacity: 1 }, { transform: 'translateX(12px)', opacity: 0 }] : [{ transform: 'translateY(0)' }, { transform: 'translateY(100%)' }];
      anim(scrim, [{ opacity: 1 }, { opacity: 0 }], { duration: 180, easing: EASE.out, fill: 'forwards' });
      anim(panel, out, { duration: 180, easing: EASE.out, fill: 'forwards' }).finished.then(() => layer.remove());
    }

    // ---- render ----
    function render() {
      const keepScroll = body.scrollTop;
      barHolder.replaceChildren(titleBar({ file: FILE_NAMES[topic] || 'main.py', meta, check: st.phase === 'result' && st.correct }));
      body.textContent = '';
      body.append(el('h2', { id: titleId, class: 'pz-title cm', text: `# ${title} · ${TYPE_LABEL[puzzle.type]}` }), el('p', { class: 'prompt', text: puzzle.prompt }));
      if (intro) body.append(tutorNote({ text: intro, source: introSource, cls: 'explain' }));

      if (puzzle.type === 'fill_blank') {
        const chosen = puzzle.options.find((o) => o.id === st.option);
        body.append(codeBlock(puzzle.code, { slot: { text: chosen ? chosen.text : '' } }), outputBox(), optionKeys());
      } else if (puzzle.type === 'predict_output') {
        body.append(codeBlock(puzzle.code), comment('Đầu ra của chương trình là:', 'sub'), optionKeys());
      } else if (puzzle.type === 'parsons') {
        body.append(outputBox(), parsonsWidget());
      } else {
        body.append(outputBox(), findBugWidget());
      }

      if (st.hints.length) {
        const hl = el('ol', { class: 'hints', 'aria-live': 'polite' });
        st.hints.forEach((t, i) => hl.append(el('li', {}, comment(`Gợi ý ${i + 1}: ${t}`))));
        body.append(hl);
      }
      if (st.note) body.append(el('p', { class: 'msg-err', role: 'alert', text: st.note }));
      if (st.error) body.append(el('p', { class: 'msg-err', role: 'alert' }, icon('x', { size: 14 }), st.error));

      if (st.phase === 'result') body.append(resultPanel());
      else body.append(footer());
      if (standalone && st.phase !== 'result' && st.phase !== 'sending') {
        body.append(el('button', { class: 'btn', type: 'button', text: closeLabel, onclick: finish }));
      }
      body.scrollTop = keepScroll;
    }

    function outputBox() {
      if (!puzzle.expected_output) return document.createDocumentFragment();
      return terminal(puzzle.expected_output, { label: 'đầu ra mong đợi' });
    }

    function attemptsDots() {
      if (maxAttempts <= 1) return null;
      const dots = el('div', { class: 'dots', role: 'img', 'aria-label': `Còn ${maxAttempts - st.attempts} lần thử` });
      for (let i = 0; i < maxAttempts; i++) dots.append(el('i', { class: i < st.attempts ? 'used' : '' }));
      return el('div', { class: 'attempts' }, el('span', { text: 'Lượt thử' }), dots);
    }

    function footer() {
      const next = st.hints.length + 1;
      const busy = st.phase === 'sending';

      if (st.phase === 'confirm') {
        st.primary = submit;
        return el('div', { class: 'confirm', role: 'group', 'aria-label': 'Xác nhận' },
          el('p', { class: 'confirm-q', text: 'Commit câu trả lời này? Chỉ có 1 lần.' }),
          el('div', { class: 'foot-row' },
            enterKey('Commit', submit),
            el('button', { class: 'btn', type: 'button', text: 'Xem lại', onclick: () => { st.phase = 'answer'; render(); } })));
      }

      const hintBtn = next <= 3
        ? el('button', { class: 'btn hint-btn', type: 'button', disabled: busy, onclick: showHint },
            icon('bulb', { size: 18 }), `Gợi ý ${next}/3`, el('span', { class: 'pen', text: ' · ' + penaltyText(next) }))
        : el('span', { class: 'hint-done', text: 'Đã xem hết gợi ý' });
      const go = () => (maxAttempts === 1 ? ((st.phase = 'confirm'), render()) : submit());
      st.primary = complete() && !busy ? go : null;
      const commit = enterKey(busy ? 'Đang chấm…' : 'Chạy kiểm tra', go, { disabled: !complete() || busy });
      return el('div', { class: 'foot' }, attemptsDots(), el('div', { class: 'foot-row' }, hintBtn, commit));
    }

    function playerText() {
      const chosen = puzzle.options?.find((o) => o.id === st.option);
      if (puzzle.type === 'fill_blank') return puzzle.code.replace('___', chosen ? chosen.text : '');
      if (puzzle.type === 'predict_output') return chosen ? chosen.text : '';
      if (puzzle.type === 'parsons') return st.order.map((o) => '    '.repeat(o.indent) + lineById(o.id).text).join('\n');
      return puzzle.lines.map((l) => '    '.repeat(l.indent) + (chosen && l.id === optLine(chosen) ? chosen.text : l.text)).join('\n');
    }

    function explainControl() {
      if (!st.wrongAnswer) return null;
      const note = el('div', { 'aria-live': 'polite' });
      const button = el('button', { class: 'btn', type: 'button', text: 'Vì sao mình sai?' });
      button.addEventListener('click', async () => {
        button.disabled = true;
        note.replaceChildren(tutorNote({ loading: true }));
        try {
          const result = await api.explainChoice(puzzle.id, st.wrongAnswer);
          note.replaceChildren(tutorNote({ text: result.text, source: result.source, cls: 'explain' }));
          button.hidden = true;
        } catch (e) {
          note.textContent = 'Không tải được giải thích: ' + e.message;
          button.disabled = false;
        }
      });
      return el('div', {}, button, note);
    }

    function resultPanel() {
      const r = st.response;
      st.primary = finish;
      if (st.correct) {
        const txt = awardText ? awardText(maxHint()) : null;
        return el('div', { class: 'res ok', role: 'status' },
          el('div', { class: 'res-title' }, icon('check', { size: 20 }), 'Chính xác!'),
          txt ? el('div', { class: 'res-pts', text: txt }) : null,
          explainControl(),
          enterKey('Tiếp tục', finish, { id: 'pz-continue' }));
      }
      const sol = r.solution_code
        ? puzzle.type === 'predict_output' ? r.solution_code.replace(/^Đầu ra:\s*/i, '') : r.solution_code
        : null;
      return el('div', { class: 'res bad', role: 'status' },
        el('div', { class: 'res-title' }, icon('x', { size: 20 }), 'Chưa đúng'),
        r.message ? el('p', { class: 'res-msg', text: r.message }) : null,
        r.actual_output ? terminal(r.actual_output, { label: 'đầu ra thực tế' }) : null,
        sol ? diffView(playerText(), sol) : null,
        r.explanation ? comment(r.explanation, 'explain') : null,
        explainControl(),
        enterKey('Tiếp tục', finish, { id: 'pz-continue' }));
    }

    // ---- mount ----
    root.append(layer);
    app.inert = true;
    gameScreen.classList.add('dim');
    document.body.classList.add('modal-open');
    dock();
    render();
    panel.focus({ preventScroll: true });
    anim(scrim, [{ opacity: 0 }, { opacity: 1 }], { duration: 260, easing: EASE.out, fill: 'backwards' });
    anim(panel,
      desktop()
        ? [{ transform: 'translateX(24px)', opacity: 0 }, { transform: 'none', opacity: 1 }]
        : [{ transform: 'translateY(100%)' }, { transform: 'translateY(0)' }],
      { duration: desktop() ? 260 : 340, easing: desktop() ? EASE.out : EASE.drawer, fill: 'backwards' });
    if (reducedMotion()) panel.style.opacity = '1';
  });
}
