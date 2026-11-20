import { richText } from './editor.js';

const sentenceSegmenter = Intl.Segmenter && new Intl.Segmenter(undefined, { granularity: 'sentence' });
const maskInlineCode = (text) => text.replace(/`[^`\n]+`/g, (code) => 'x'.repeat(code.length));

function sentences(text) {
  if (!sentenceSegmenter) return [text];
  // Mask inline code while finding boundaries so a decimal or a quoted string stays intact.
  return Array.from(sentenceSegmenter.segment(maskInlineCode(text)),
    ({ index, segment }) => text.slice(index, index + segment.length));
}

function phrases(sentence) {
  const words = [...maskInlineCode(sentence).matchAll(/\S+/gu)];
  if (words.length < 7) return [sentence];
  const size = Math.ceil(words.length / Math.ceil(words.length / 5));
  const result = [];
  let start = 0;
  for (let i = size; i < words.length; i += size) {
    result.push(sentence.slice(start, words[i].index));
    start = words[i].index;
  }
  result.push(sentence.slice(start));
  return result;
}

const weight = (text) => Math.max(1, (text.match(/[\p{L}\p{N}]/gu) || []).length);
const sum = (values) => values.reduce((total, value) => total + value, 0);

function phraseTimes(buffer, weights) {
  const samples = buffer.getChannelData(0);
  const frameSize = Math.max(1, Math.round(buffer.sampleRate * 0.02));
  const levels = [];
  for (let i = 0; i < samples.length; i += frameSize) {
    let energy = 0;
    const end = Math.min(samples.length, i + frameSize);
    for (let j = i; j < end; j += 4) energy += samples[j] ** 2;
    levels.push(Math.sqrt(energy / Math.ceil((end - i) / 4)));
  }
  const step = frameSize / buffer.sampleRate;
  const threshold = Math.max(0.003, Math.max(...levels) * 0.06);
  const voiced = [];
  const pauses = [];
  for (const [frame, level] of levels.entries()) {
    if (level < threshold) continue;
    if (voiced.length && frame - voiced.at(-1) >= 5) pauses.push(frame * step);
    voiced.push(frame);
  }

  // Estimate phrase starts using the clip's voiced time and nearby pauses.
  const total = sum(weights);
  let progress = 0;
  let previous = -Infinity;
  return weights.map((value, index) => {
    const fraction = progress / total;
    progress += value;
    const guess = voiced.length ? voiced[Math.floor(fraction * voiced.length)] * step : fraction * buffer.duration;
    let boundary = guess;
    if (index) {
      let distance = 0.25;
      for (const pause of pauses) {
        const difference = Math.abs(pause - guess);
        if (pause > previous + 0.16 && difference < distance) {
          boundary = pause;
          distance = difference;
        }
      }
    }
    previous = Math.max(previous, boundary);
    return previous;
  });
}

export function createFollowAlong(text, transcript) {
  const written = sentences(text);
  const spoken = typeof transcript === 'string' ? sentences(transcript) : written;
  const spans = [];
  const weights = [];
  for (const [index, sentence] of written.entries()) {
    const parts = phrases(sentence);
    const partWeights = parts.map(weight);
    const total = sum(partWeights);
    const spokenWeight = written.length === spoken.length ? weight(spoken[index]) : total;
    for (const [i, part] of parts.entries()) {
      const span = document.createElement('span');
      span.className = 'mk-phrase';
      span.append(richText(part));
      spans.push(span);
      weights.push(partWeights[i] / total * spokenWeight);
    }
  }

  let frame;
  let active = -1;
  function highlight(index) {
    if (index === active) return;
    spans[active]?.classList.remove('is-speaking');
    spans[index]?.classList.add('is-speaking');
    active = index;
  }
  function stop() {
    cancelAnimationFrame(frame);
    highlight(-1);
  }
  function start(buffer, elapsed) {
    const times = phraseTimes(buffer, weights);
    function update() {
      const time = elapsed();
      highlight(times.findLastIndex((boundary) => boundary <= time));
      frame = requestAnimationFrame(update);
    }
    update();
  }
  return { spans, start, stop };
}
