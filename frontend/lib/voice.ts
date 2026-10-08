// Speaks replies with the backend's local Piper voices. ULTRON's voice
// is processed here: pitched down, with a metallic comb resonance and
// more low end. The analyser's level drives the orb while speaking.
import type { Mode } from "@/lib/mode";

const BASE = "/api/jarvis";

interface Effect {
  // <1 lowers pitch (and slows; the backend renders ULTRON faster to compensate).
  playbackRate: number;
  // Comb filter: a short feedback delay gives a metallic, robotic ring.
  combDelay?: number;
  combFeedback?: number;
  combMix?: number;
  bassBoostDb?: number;
}

const EFFECTS: Record<Mode, Effect> = {
  jarvis: { playbackRate: 1 },
  ultron: { playbackRate: 0.86, combDelay: 0.011, combFeedback: 0.45, combMix: 0.45, bassBoostDb: 5 },
};

export interface VoiceStatus {
  /** Which modes have a voice installed. */
  available: Record<Mode, boolean>;
  /** The wake word models are installed. */
  wake_word: boolean;
}

export async function voiceStatus(): Promise<VoiceStatus> {
  try {
    const res = await fetch(`${BASE}/voice/status`, { cache: "no-store" });
    if (!res.ok) throw new Error();
    return await res.json();
  } catch {
    return { available: { jarvis: false, ultron: false }, wake_word: false };
  }
}

export class VoicePlayer {
  private ctx: AudioContext | null = null;
  private source: AudioBufferSourceNode | null = null;
  private abort: AbortController | null = null;
  private rafId = 0;
  private loading = false;

  constructor(private onLevel: (level: number) => void) {}

  /**
   * Browsers only allow audio after a user gesture; call this from a
   * click or key handler (e.g. turning voice on, sending a message).
   */
  unlock() {
    this.ctx ??= new AudioContext();
    void this.ctx.resume();
  }

  /** Fetching or playing speech. */
  get speaking(): boolean {
    return this.loading || this.source !== null;
  }

  /** Speaks `text`, interrupting anything already playing. */
  async speak(text: string, mode: Mode): Promise<void> {
    this.stop();
    this.unlock();
    const ctx = this.ctx!;

    const abort = new AbortController();
    this.abort = abort;

    this.loading = true;
    let audio: AudioBuffer;
    try {
      const res = await fetch(`${BASE}/voice/speak`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text, mode }),
        signal: abort.signal,
      });
      if (!res.ok) throw new Error(`voice ${res.status}`);

      audio = await ctx.decodeAudioData(await res.arrayBuffer());
    } finally {
      if (this.abort === abort) this.loading = false;
    }
    if (abort.signal.aborted) return;

    const source = ctx.createBufferSource();
    source.buffer = audio;
    const output = this.chain(ctx, source, EFFECTS[mode]);

    const analyser = ctx.createAnalyser();
    analyser.fftSize = 512;
    output.connect(analyser);
    analyser.connect(ctx.destination);

    this.source = source;
    this.meter(analyser);

    await new Promise<void>((resolve) => {
      source.onended = () => resolve();
      abort.signal.addEventListener("abort", () => resolve());
      source.start();
    });

    if (this.source === source) this.finish();
  }

  stop() {
    this.abort?.abort();
    this.abort = null;
    this.loading = false;
    try {
      this.source?.stop();
    } catch {
      // Not started yet.
    }
    this.finish();
  }

  private finish() {
    cancelAnimationFrame(this.rafId);
    this.source = null;
    this.onLevel(0);
  }

  private chain(ctx: AudioContext, source: AudioBufferSourceNode, effect: Effect): AudioNode {
    source.playbackRate.value = effect.playbackRate;
    let node: AudioNode = source;

    if (effect.bassBoostDb) {
      const bass = ctx.createBiquadFilter();
      bass.type = "lowshelf";
      bass.frequency.value = 180;
      bass.gain.value = effect.bassBoostDb;
      node.connect(bass);
      node = bass;
    }

    if (effect.combDelay) {
      // dry + (delay with feedback) -> mix
      const mix = ctx.createGain();
      const wet = ctx.createGain();
      const delay = ctx.createDelay(0.05);
      const feedback = ctx.createGain();
      delay.delayTime.value = effect.combDelay;
      feedback.gain.value = effect.combFeedback ?? 0.4;
      wet.gain.value = effect.combMix ?? 0.4;

      node.connect(mix);
      node.connect(delay);
      delay.connect(feedback);
      feedback.connect(delay);
      delay.connect(wet);
      wet.connect(mix);
      node = mix;
    }

    // Keeps loudness even (the comb and bass boost add peaks).
    const compressor = ctx.createDynamicsCompressor();
    compressor.threshold.value = -18;
    compressor.ratio.value = 4;
    node.connect(compressor);
    return compressor;
  }

  /** Reports a smoothed 0..1 loudness each frame while speaking. */
  private meter(analyser: AnalyserNode) {
    const samples = new Float32Array(analyser.fftSize);
    let level = 0;

    const tick = () => {
      analyser.getFloatTimeDomainData(samples);
      let sum = 0;
      for (const s of samples) sum += s * s;
      const rms = Math.sqrt(sum / samples.length);
      level += (Math.min(1, rms * 5) - level) * 0.35;
      this.onLevel(level);
      this.rafId = requestAnimationFrame(tick);
    };
    tick();
  }
}
