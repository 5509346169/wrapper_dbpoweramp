// Waveform animator — reads <figure data-waveform> nodes and replaces
// the three <path> children with sampled sine + harmonics + noise.
// prefers-reduced-motion freezes on the first frame.

const TAU = Math.PI * 2;
const SAMPLES_DEFAULT = 96;

function pathFromSamples(samples) {
  const stepX = 800 / (samples.length - 1);
  let d = `M 0 ${100 + samples[0]}`;
  for (let i = 1; i < samples.length; i++) {
    d += ` L ${(i * stepX).toFixed(2)} ${(100 + samples[i]).toFixed(2)}`;
  }
  return d;
}

function carrier(t, density) {
  const out = new FloatArray(density);
  for (let i = 0; i < density; i++) {
    out[i] = Math.sin((i / density) * TAU * 6 + t) * 28;
  }
  return out;
}

function harmonics(t, density) {
  const out = new FloatArray(density);
  for (let i = 0; i < density; i++) {
    const x = (i / density) * TAU;
    out[i] =
      Math.sin(x * 12 + t * 0.7) * 6 +
      Math.sin(x * 18 + t * 0.4) * 3 +
      Math.sin(x * 24 - t * 0.9) * 1.5;
  }
  return out;
}

function noise(density) {
  const out = new FloatArray(density);
  for (let i = 0; i < density; i++) out[i] = (Math.random() - 0.5) * 1.2;
  return out;
}

function freezeAll(fig) {
  const density = parseInt(fig.dataset.density || SAMPLES_DEFAULT, 10);
  const c = fig.querySelector(".waveform__carrier");
  const h = fig.querySelector(".waveform__harmonics");
  const n = fig.querySelector(".waveform__noise");
  if (c) c.setAttribute("d", pathFromSamples(carrier(0, density)));
  if (h) h.setAttribute("d", pathFromSamples(harmonics(0, density)));
  if (n) n.setAttribute("d", pathFromSamples(noise(density)));
}

function start(fig) {
  const density = parseInt(fig.dataset.density || SAMPLES_DEFAULT, 10);
  const c = fig.querySelector(".waveform__carrier");
  const h = fig.querySelector(".waveform__harmonics");
  const n = fig.querySelector(".waveform__noise");
  let t = 0;
  function tick() {
    t += 0.04;
    if (c) c.setAttribute("d", pathFromSamples(carrier(t, density)));
    if (h) h.setAttribute("d", pathFromSamples(harmonics(t, density)));
    if (n) n.setAttribute("d", pathFromSamples(noise(density)));
    fig._raf = requestAnimationFrame(tick);
  }
  tick();
}

function init() {
  const figs = document.querySelectorAll("[data-waveform]");
  const reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  figs.forEach((fig) => {
    if (reduce) freezeAll(fig);
    else start(fig);
  });
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init, { once: true });
} else {
  init();
}
