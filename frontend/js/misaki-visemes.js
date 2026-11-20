// Approximate A, I, U, E and O from the first two resonances of the speech.
const CENTERS = [[780, 1480], [320, 2570], [320, 1190], [510, 2190], [515, 1020]];
const ORDER = 10;
const BIN_HZ = 40;

export function createVisemeSampler(analyser, sampleRate) {
  analyser.fftSize = 2048;
  const samples = new Float32Array(analyser.fftSize);
  const stride = Math.max(1, Math.round(sampleRate / 11000));
  const rate = sampleRate / stride;
  const signal = new Float64Array(Math.floor(samples.length / stride));
  const window = signal.map((_, i) => 0.5 - 0.5 * Math.cos(2 * Math.PI * i / (signal.length - 1)));
  const auto = new Float64Array(ORDER + 1);
  const coeff = new Float64Array(ORDER + 1);
  const previous = new Float64Array(ORDER + 1);
  const frequencies = Array.from({ length: 85 }, (_, i) => {
    const radians = i * BIN_HZ * 2 * Math.PI / rate;
    return [windowTerms(Math.cos, radians), windowTerms(Math.sin, radians)];
  });
  const spectrum = new Float64Array(frequencies.length);
  const face = { opening: 0, vowels: new Float32Array(CENTERS.length) };

  function trackFormants() {
    let prior = 0;
    for (let i = 0; i < signal.length; i++) {
      let value = 0;
      for (let j = 0; j < stride; j++) value += samples[i * stride + j];
      signal[i] = (value - 0.96 * prior) * window[i];
      prior = value;
    }
    for (let lag = 0; lag <= ORDER; lag++) {
      let sum = 0;
      for (let i = lag; i < signal.length; i++) sum += signal[i] * signal[i - lag];
      auto[lag] = sum;
    }

    // Levinson-Durbin recursion gives a spectral envelope independent of the voice pitch.
    coeff.fill(0);
    let error = auto[0] * 1.001;
    for (let lag = 1; lag <= ORDER; lag++) {
      let residual = auto[lag];
      for (let i = 1; i < lag; i++) residual += coeff[i] * auto[lag - i];
      if (error < 1e-10) return -1;
      const reflection = -residual / error;
      previous.set(coeff);
      coeff[lag] = reflection;
      for (let i = 1; i < lag; i++) coeff[i] = previous[i] + reflection * previous[lag - i];
      error *= 1 - reflection * reflection;
    }
    for (let bin = 5; bin < spectrum.length; bin++) {
      const [cosines, sines] = frequencies[bin];
      let real = 1;
      let imaginary = 0;
      for (let i = 1; i <= ORDER; i++) {
        real += coeff[i] * cosines[i];
        imaginary += coeff[i] * sines[i];
      }
      spectrum[bin] = 1 / (real * real + imaginary * imaginary);
    }

    let first = 0;
    let second = 0;
    for (let bin = 6; bin < spectrum.length - 1; bin++) {
      if (spectrum[bin] <= spectrum[bin - 1] || spectrum[bin] <= spectrum[bin + 1]) continue;
      const frequency = bin * BIN_HZ;
      if (!first && frequency <= 1080) first = frequency;
      else if (first && frequency >= Math.max(680, first + 240)) {
        second = frequency;
        break;
      }
    }
    if (!second) return -1;
    let match = -1;
    let closest = Infinity;
    for (const [i, [f1, f2]] of CENTERS.entries()) {
      const distance = ((first - f1) / 220) ** 2 + ((second - f2) / 520) ** 2;
      if (distance < closest) {
        match = i;
        closest = distance;
      }
    }
    return closest < 4 ? match : -1;
  }

  return () => {
    analyser.getFloatTimeDomainData(samples);
    let energy = 0;
    for (const sample of samples) energy += sample * sample;
    const level = Math.sqrt(energy / samples.length);
    const opening = Math.max(0, Math.min(1, (level - 0.012) * 7));
    face.opening += (opening - face.opening) * (opening > face.opening ? 0.65 : 0.40);
    const vowel = level >= 0.028 ? trackFormants() : -1;
    const strength = Math.min(1, opening * 1.45);
    for (let i = 0; i < face.vowels.length; i++) {
      face.vowels[i] += ((i === vowel ? strength : 0) - face.vowels[i]) * 0.55;
    }
    return face;
  };
}

function windowTerms(wave, radians) {
  return Float64Array.from({ length: ORDER + 1 }, (_, i) => wave(i * radians));
}
