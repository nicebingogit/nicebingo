// Synthesized sound effects via the Web Audio API — zero audio files needed.
// Each effect layers a fundamental tone with a quieter harmonic overtone so
// the sounds feel fuller and more satisfying (players want that dopamine hit).
export const PACKS = [
  { id: 'classic', label: '🎵 Classic' },
  { id: 'retro', label: '👾 Retro' },
  { id: 'digital', label: '🔊 Digital' },
  { id: 'mute', label: '🔇 Mute' },
];

let current = 'classic';
let ctx = null;

export const setPack = (id) => { current = id; };
export const getPack = () => current;

function ensure() {
  if (!ctx) {
    const AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) return null;
    ctx = new AC();
  }
  if (ctx.state === 'suspended') ctx.resume();
  return ctx;
}

// A single tone: frequency `freq`, waveform `type`, duration `dur` seconds,
// peak `gain`. `slideTo` bends the pitch (nice for whooshes and sad trombones).
// When `harmonic` is set a second oscillator an octave up rings quietly on top
// for a warmer, richer timbre.
function tone(freq, type, dur, gain, delay = 0, slideTo = null, harmonic = true) {
  if (current === 'mute') return;
  const c = ensure();
  if (!c) return;
  const t0 = c.currentTime + delay;
  const osc = c.createOscillator();
  const g = c.createGain();
  osc.type = type;
  osc.frequency.setValueAtTime(freq, t0);
  if (slideTo) osc.frequency.exponentialRampToValueAtTime(Math.max(20, slideTo), t0 + dur);
  g.gain.setValueAtTime(0.0001, t0);
  g.gain.exponentialRampToValueAtTime(gain, t0 + 0.015);
  g.gain.exponentialRampToValueAtTime(0.0001, t0 + dur);
  osc.connect(g);
  g.connect(c.destination);
  osc.start(t0);
  osc.stop(t0 + dur + 0.05);
  if (harmonic) {
    const osc2 = c.createOscillator();
    const g2 = c.createGain();
    osc2.type = type;
    osc2.frequency.setValueAtTime(freq * 2, t0);
    g2.gain.setValueAtTime(0.0001, t0);
    g2.gain.exponentialRampToValueAtTime(gain * 0.28, t0 + 0.015);
    g2.gain.exponentialRampToValueAtTime(0.0001, t0 + dur * 0.8);
    osc2.connect(g2);
    g2.connect(c.destination);
    osc2.start(t0);
    osc2.stop(t0 + dur * 0.8 + 0.05);
  }
}

const wave = () => (current === 'retro' ? 'square' : current === 'digital' ? 'triangle' : 'sine');

// Each letter of BINGO has its own pitch family.
const LETTER_FREQ = { B: 220, I: 277, N: 330, G: 392, O: 440 };

// A bright two-note "bling" — the freshly drawn ball feels rewarding.
export function playBall(number) {
  const letter = String(number || '').split('-')[0];
  const base = LETTER_FREQ[letter] || 330;
  tone(base, wave(), 0.16, 0.26);
  tone(base * 1.5, wave(), 0.22, 0.16, 0.08);
  tone(base * 2, wave(), 0.2, 0.08, 0.14, null, false); // sparkle on top
}

// A satisfying "pop" when the player daubs a number on their card — a soft
// thump with a click, like stamping a paper card.
export function playDaub() {
  tone(190, 'triangle', 0.09, 0.3, 0, 120, false);
  tone(1500, wave(), 0.05, 0.12, 0.01, 900, false);
}

// Rising fanfare that announces the round.
export function playRoundStart() {
  [261.6, 329.6, 392, 523.3, 659.3].forEach((f, i) => tone(f, wave(), 0.2, 0.18, i * 0.1));
}

// Triumphant ascending fanfare with a final chord — winning feels amazing.
export function playWin() {
  [523.3, 659.3, 784, 1046.5, 1318.5, 1568].forEach((f, i) => tone(f, wave(), 0.3, 0.22, i * 0.12));
  [523.3, 659.3, 1046.5].forEach((f) => tone(f, wave(), 0.55, 0.16, 0.78));
}

// Gentle "so close" descent.
export function playLose() {
  tone(392, wave(), 0.25, 0.16, 0, 330);
  tone(330, wave(), 0.32, 0.16, 0.2, 262);
}

export function playCountdown() {
  tone(440, wave(), 0.09, 0.14);
  tone(880, wave(), 0.09, 0.07, 0.06);
}

export function playClick() {
  tone(880, wave(), 0.05, 0.09, 0, null, false);
}
