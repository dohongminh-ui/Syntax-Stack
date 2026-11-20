import { misakiVoice } from './api.js';
import { readVoiceStream } from './misaki-pcm.js';
import { isRehearsalRecording, loadRehearsalRecording } from './misaki-rehearsal.js';
import { createVisemeSampler } from './misaki-visemes.js';
import { isMuted, prepareAudio } from './sound.js';

const Audio = globalThis.AudioContext || globalThis.webkitAudioContext;
export const voiceSupported = Boolean(Audio);

export function createVoicePlayer(setSampler) {
  let playing;
  let clip; // keep the most recently played reply for instant replay in this tab

  function stop() {
    if (!playing) return;
    const { abort, sources, analyser, onState } = playing;
    playing = null;
    abort.abort();
    for (const source of sources) {
      source.onended = null;
      source.stop();
      source.disconnect();
    }
    analyser.disconnect();
    setSampler(null);
    onState(false);
  }

  async function play(voice, onState, onStart, onClip) {
    if (isMuted() || !voiceSupported) return;
    stop();
    const context = prepareAudio();
    if (!context) return;
    const analyser = context.createAnalyser();
    analyser.connect(context.destination);
    const key = voice.recording || voice.ticket;
    const current = { key, onState, analyser, abort: new AbortController(), sources: new Set() };
    playing = current;
    onState(true);
    const timeline = [];
    let next = 0;
    let duration = 0;
    let finished = false;

    function elapsed() {
      const now = context.currentTime;
      const block = timeline.findLast(({ at }) => at <= now);
      return block ? block.offset + Math.min(now - block.at, block.duration) : 0;
    }

    function enqueue(buffer, streamed) {
      if (playing !== current) return;
      const source = context.createBufferSource();
      source.buffer = buffer;
      source.connect(analyser);
      const first = timeline.length === 0;
      const now = context.currentTime;
      const at = next >= now && !first ? next : now + (first ? 0.015 : 0.08);
      next = at + buffer.duration;
      timeline.push({ at, offset: duration, duration: buffer.duration });
      duration += buffer.duration;
      source.onended = () => {
        current.sources.delete(source);
        source.disconnect();
        if (playing === current && finished && !current.sources.size) stop();
      };
      source.start(at);
      current.sources.add(source);
      if (first) {
        setSampler(createVisemeSampler(analyser, context.sampleRate));
        onStart(streamed ? null : buffer, elapsed);
      }
    }

    try {
      if (context.state !== 'running') await context.resume();
      if (playing !== current) return;
      if (clip?.key === key) {
        enqueue(clip.buffer, false);
      } else if (isRehearsalRecording(voice.recording)) {
        const data = await loadRehearsalRecording(voice.recording);
        if (playing !== current) return;
        const buffer = await context.decodeAudioData(data.slice(0));
        if (playing !== current) return;
        clip = { key, buffer };
        enqueue(buffer, false);
      } else {
        const response = await misakiVoice(voice.ticket, current.abort.signal);
        if (playing !== current) return;
        const streamed = response.headers.get('content-type')?.startsWith('application/octet-stream');
        const buffer = streamed
          ? await readVoiceStream(response, context, (part) => enqueue(part, true), () => next <= context.currentTime)
          : await context.decodeAudioData(await response.arrayBuffer());
        if (playing !== current) return;
        clip = { key, buffer };
        if (streamed) onClip(buffer);
        else enqueue(buffer, false);
      }
      finished = true;
      if (!current.sources.size) stop();
    } catch (error) {
      if (playing !== current) return;
      stop();
      throw error;
    }
  }

  async function toggle(voice, onState, onStart, onClip) {
    if (playing?.key === (voice.recording || voice.ticket)) stop();
    else await play(voice, onState, onStart, onClip);
  }

  return { play, toggle, stop };
}
