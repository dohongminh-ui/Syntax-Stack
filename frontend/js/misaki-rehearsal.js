export let rehearsing = false;
export const rehearsalPuzzleIdea = 'rehearsal:range-1-4';

export function beginRehearsal() {
  rehearsing = true;
}

const normalize = (text) => text.trim().toLowerCase().replace(/\s+/g, ' ').replace(/[.!?]+$/, '');
const turns = new Map([
  [
    normalize('Start a beginner Code Rescue run. I want to practice Python loops.'),
    {
      text: 'Let’s start with a beginner Code Rescue run. Solve a Python loop puzzle to clear a locked line.',
      mood: 'excited', recording: 'rescue',
      action: { type: 'rescue', mode: 'rescue', level: 'beginner', focus_topic: 'loops' },
    },
  ],
  [
    normalize('Now open Syntax Rows Level 3, Count to three. I want to build a loop with code tiles and predict its output.'),
    {
      text: 'Let’s try Count to three. Build the loop with code tiles, then predict what it prints.',
      mood: 'happy', recording: 'rows', action: { type: 'rows', level_id: 'r3' },
    },
  ],
  [
    normalize('Make a beginner Python loop puzzle set. Use a short for loop with range(1, 4), and let me predict the output before you explain it.'),
    {
      text: 'I have a short range puzzle ready. Trace the loop and predict what it prints.',
      mood: 'happy', recording: 'offer',
      action: { type: 'make_puzzle', topic: 'loops', idea: rehearsalPuzzleIdea },
    },
  ],
]);

export function rehearsalReply(text) {
  return rehearsing ? turns.get(normalize(text)) : undefined;
}

const recordings = new Set([...Array.from(turns.values(), (turn) => turn.recording), 'puzzle', 'review']);
const audio = new Map();
const version = new URL(import.meta.url).search;

export function isRehearsalRecording(id) {
  return rehearsing && recordings.has(id);
}

export function loadRehearsalRecording(id) {
  if (!audio.has(id)) {
    const request = fetch(new URL(`../audio/misaki-rehearsal/${id}.wav${version}`, import.meta.url))
      .then((response) => {
        if (!response.ok) throw new Error('Rehearsal audio is unavailable');
        return response.arrayBuffer();
      })
      .catch((error) => {
        audio.delete(id);
        throw error;
      });
    audio.set(id, request);
  }
  return audio.get(id);
}

export function preloadRehearsalAudio() {
  for (const id of recordings) loadRehearsalRecording(id).catch(() => {});
}
