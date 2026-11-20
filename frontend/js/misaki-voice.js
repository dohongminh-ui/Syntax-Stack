import { misakiVoice } from './api.js';
import { createVisemeSampler } from './misaki-visemes.js';
import { isMuted, prepareAudio } from './sound.js';

const Audio = globalThis.AudioContext || globalThis.webkitAudioContext;
export const voiceSupported = Boolean(Audio);

export function createVoicePlayer(setSampler) {
  let playing;
  let clip; // keep the most recently played reply for instant replay in this tab

  function stop() {
    if (!playing) return;
    const { source, analyser, onState } = playing;
    playing = null;
    if (source) {
      source.onended = null;
      source.stop();
      source.disconnect();
    }
    analyser?.disconnect();
    setSampler(null);
    onState(false);
  }

  async function play(ticket, onState) {
    if (isMuted() || !voiceSupported) return;
    stop();
    const context = prepareAudio();
    if (!context) return;
    const current = { ticket, onState };
    playing = current;
    onState(true);
    try {
      if (context.state !== 'running') await context.resume();
      if (playing !== current) return;
      const buffer = clip?.ticket === ticket ? clip.buffer
        : await context.decodeAudioData(await misakiVoice(ticket));
      if (playing !== current) return;
      clip = { ticket, buffer };

      const analyser = context.createAnalyser();
      current.analyser = analyser;
      const source = context.createBufferSource();
      source.buffer = buffer;
      source.connect(analyser);
      analyser.connect(context.destination);
      source.onended = () => {
        if (playing === current) stop();
      };
      setSampler(createVisemeSampler(analyser, context.sampleRate));
      source.start();
      current.source = source;
    } catch (error) {
      if (playing !== current) return;
      stop();
      throw error;
    }
  }

  async function toggle(ticket, onState) {
    if (playing?.ticket === ticket) stop();
    else await play(ticket, onState);
  }

  return { play, toggle, stop };
}
