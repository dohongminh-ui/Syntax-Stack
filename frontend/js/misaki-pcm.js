const SAMPLE_RATE = 24000;

// Read raw little-endian 16-bit mono PCM. HTTP chunks can end in the middle of a sample.
export async function readVoiceStream(response, context, enqueue, needsBuffer) {
  const reader = response.body.getReader();
  const clips = [];
  let pending = [];
  let length = 0;
  let frames = 0;

  function flush() {
    const bytes = new Uint8Array(length);
    let offset = 0;
    for (const chunk of pending) {
      bytes.set(chunk, offset);
      offset += chunk.length;
    }
    const samples = length >> 1;
    length %= 2;
    pending = length ? [bytes.subarray(bytes.length - 1)] : [];
    if (!samples) return;
    const buffer = context.createBuffer(1, samples, SAMPLE_RATE);
    const target = buffer.getChannelData(0);
    const pcm = new DataView(bytes.buffer);
    for (let i = 0; i < samples; i++) target[i] = pcm.getInt16(i * 2, true) / 32768;
    clips.push(buffer);
    frames += samples;
    enqueue(buffer);
  }

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      pending.push(value);
      length += value.length;
      const seconds = needsBuffer() ? 0.3 : 0.1;
      if (length >= SAMPLE_RATE * 2 * seconds) flush();
    }
    if (length % 2) throw new Error('Incomplete Misaki voice stream');
    if (length) flush();
    if (!clips.length) throw new Error('Empty Misaki voice stream');
  } finally {
    reader.releaseLock();
  }

  if (clips.length === 1) return clips[0];
  const full = context.createBuffer(1, frames, SAMPLE_RATE);
  let offset = 0;
  for (const clip of clips) {
    full.copyToChannel(clip.getChannelData(0), 0, offset);
    offset += clip.length;
  }
  return full;
}
