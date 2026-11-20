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

const transcripts = {
  rescue: {
    vi: 'Bắt đầu với Code Rescue cấp độ cơ bản nhé. Giải một câu đố Python về vòng lặp để xóa một hàng bị khóa.',
    ja: 'まずは初心者向けのコードレスキューから始めよう。パイソンのループ問題を解いて、ロックされた段を一つ消してみてね。',
  },
  rows: {
    vi: 'Cùng thử màn Đếm đến ba nhé. Hãy ghép các mảnh mã thành vòng lặp rồi đoán xem chương trình in ra gì.',
    ja: '「三まで数える」に挑戦しよう。コードのタイルでループを作って、何が表示されるか予想してみてね。',
  },
  offer: {
    vi: 'Mình có sẵn một câu đố ngắn về hàm range. Hãy theo dõi vòng lặp và đoán xem nó in ra gì.',
    ja: 'レンジ関数の短い問題を用意したよ。ループをたどって、何が表示されるか予想してみてね。',
  },
  puzzle: {
    vi: 'Câu đố vòng lặp của bạn đây. Hãy đoán xem chương trình in ra gì trước khi kiểm tra đáp án nhé.',
    ja: 'ループの問題だよ。答えを確認する前に、何が表示されるか予想してみてね。',
  },
  review: {
    vi: 'Dự đoán đầu tiên chưa đúng. Ở lượt thử lại, bạn đã tìm ra một, hai và ba. Vòng lặp dừng trước số bốn.',
    ja: '最初の予想はちょっと違ったね。やり直したら、一、二、三と正しく予想できたよ。ループは四の手前で止まるんだ。',
  },
};
const audio = new Map();
const version = new URL(import.meta.url).search;

export function isRehearsalRecording(id) {
  return rehearsing && Object.hasOwn(transcripts, id);
}

export function rehearsalVoice(recording, language) {
  return { recording, language, transcript: transcripts[recording]?.[language] };
}

export function loadRehearsalRecording(id, language) {
  const suffix = Object.hasOwn(transcripts[id], language) ? `.${language}` : '';
  const filename = `${id}${suffix}.wav`;
  if (!audio.has(filename)) {
    const request = fetch(new URL(`../audio/misaki-rehearsal/${filename}${version}`, import.meta.url))
      .then((response) => {
        if (!response.ok) throw new Error('Rehearsal audio is unavailable');
        return response.arrayBuffer();
      })
      .catch((error) => {
        audio.delete(filename);
        throw error;
      });
    audio.set(filename, request);
  }
  return audio.get(filename);
}

export function preloadRehearsalAudio(language) {
  for (const id of Object.keys(transcripts)) loadRehearsalRecording(id, language).catch(() => {});
}
