// Tiny Python highlighter with a restrained palette (keywords Coral, strings Matcha, numbers Mustard, functions Ice).
const KW = new Set(['for', 'in', 'if', 'else', 'elif', 'while', 'def', 'return', 'and', 'or', 'not', 'True', 'False', 'None', 'import', 'from', 'as', 'break', 'continue', 'pass']);
const RE = /(#.*$)|("(?:[^"\\]|\\.)*"?|'(?:[^'\\]|\\.)*'?)|(\b\d+(?:\.\d+)?\b)|([A-Za-z_À-ỹ][\wÀ-ỹ]*)|(\s+)|([\s\S])/gu;

function span(cls, text) {
  const s = document.createElement('span');
  s.className = cls;
  s.textContent = text;
  return s;
}

/** Returns a DocumentFragment of highlighted spans for one line of Python. */
export function highlightPy(src) {
  const frag = document.createDocumentFragment();
  RE.lastIndex = 0;
  let m;
  while ((m = RE.exec(src)) !== null) {
    if (m[1]) frag.append(span('sx-cm', m[1]));
    else if (m[2]) frag.append(span('sx-str', m[2]));
    else if (m[3]) frag.append(span('sx-num', m[3]));
    else if (m[4]) {
      const id = m[4];
      if (KW.has(id)) frag.append(span('sx-kw', id));
      else if (src[RE.lastIndex] === '(') frag.append(span('sx-fn', id));
      else frag.append(document.createTextNode(id));
    } else frag.append(document.createTextNode(m[5] || m[6]));
  }
  return frag;
}
