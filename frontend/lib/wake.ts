// Wake word: while on, the mic stays open and the latest 2.5s of audio
// (16 kHz, 16-bit) goes to the backend every half second, where a local
// openWakeWord model listens for "Hey Jarvis". Nothing is recorded or
// kept; each window is scored and dropped.

import { apiFetch } from "@/lib/auth";

const BASE = "/api/jarvis";

const RATE = 16_000;
const WINDOW = RATE * 2.5;
const HOP = RATE * 0.5;
// After a detection (or a pause) a fresh 2s must be heard, so the same
// "Hey Jarvis", or Jarvis's own voice, isn't scored again.
const MIN_FRESH = RATE * 2;

// Collects mic frames off the main thread and posts ~85 ms batches.
const WORKLET = `
class Tap extends AudioWorkletProcessor {
  constructor() { super(); this.buf = new Float32Array(4096); this.n = 0; }
  process(inputs) {
    const ch = inputs[0][0];
    if (ch) {
      this.buf.set(ch, this.n);
      this.n += ch.length;
      if (this.n + 128 > this.buf.length) {
        this.port.postMessage(this.buf.slice(0, this.n));
        this.n = 0;
      }
    }
    return true;
  }
}
registerProcessor("wake-tap", Tap);
`;

export class WakeWordUnavailable extends Error {}

interface WakeOptions {
  /** "Hey Jarvis" was heard. */
  onWake(): void;
  /** Listening stopped for good (models missing, mic lost). */
  onError(error: Error): void;
  /**
   * Whether to listen right now; e.g. not while already recording,
   * waiting for a reply or speaking (Jarvis would wake himself).
   */
  active(): boolean;
}

export class WakeListener {
  private stream: MediaStream | null = null;
  private ctx: AudioContext | null = null;
  private window = new Int16Array(WINDOW);
  private filled = 0;
  private sinceSent = 0;
  private inFlight = false;
  private stopped = true;
  private resampler: Resampler | null = null;
  private resumeOnGesture: (() => void) | null = null;

  constructor(private options: WakeOptions) {}

  async start(): Promise<void> {
    if (!this.stopped) return;
    this.stopped = false;

    const stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    });
    if (this.stopped) {
      stream.getTracks().forEach((t) => t.stop());
      return;
    }
    this.stream = stream;
    // Mic unplugged or permission revoked.
    stream.getAudioTracks()[0]?.addEventListener("ended", () => {
      this.stop();
      this.options.onError(new Error("MICROPHONE LOST"));
    });

    const ctx = new AudioContext();
    this.ctx = ctx;
    this.resampler = new Resampler(ctx.sampleRate, RATE);

    const url = URL.createObjectURL(new Blob([WORKLET], { type: "text/javascript" }));
    try {
      await ctx.audioWorklet.addModule(url);
    } finally {
      URL.revokeObjectURL(url);
    }
    if (this.stopped) return;

    const tap = new AudioWorkletNode(ctx, "wake-tap");
    tap.port.onmessage = (e: MessageEvent<Float32Array>) => this.push(e.data);
    ctx.createMediaStreamSource(stream).connect(tap);

    // Restored on page load (no click yet): browsers keep audio
    // suspended until the first interaction.
    await ctx.resume().catch(() => {});
    if (ctx.state !== "running") {
      const resume = () => void ctx.resume();
      this.resumeOnGesture = resume;
      window.addEventListener("pointerdown", resume, { once: true });
      window.addEventListener("keydown", resume, { once: true });
    }
  }

  stop() {
    this.stopped = true;
    if (this.resumeOnGesture) {
      window.removeEventListener("pointerdown", this.resumeOnGesture);
      window.removeEventListener("keydown", this.resumeOnGesture);
      this.resumeOnGesture = null;
    }
    this.stream?.getTracks().forEach((t) => t.stop());
    void this.ctx?.close();
    this.stream = null;
    this.ctx = null;
    this.reset();
  }

  /** A soft two-note chime: "I'm listening". */
  chime() {
    const ctx = this.ctx;
    if (!ctx || ctx.state !== "running") return;
    const now = ctx.currentTime;
    [660, 880].forEach((freq, i) => {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.frequency.value = freq;
      const t = now + i * 0.09;
      gain.gain.setValueAtTime(0, t);
      gain.gain.linearRampToValueAtTime(0.08, t + 0.01);
      gain.gain.exponentialRampToValueAtTime(0.0001, t + 0.12);
      osc.connect(gain).connect(ctx.destination);
      osc.start(t);
      osc.stop(t + 0.13);
    });
  }

  private reset() {
    this.filled = 0;
    this.sinceSent = 0;
  }

  private push(frame: Float32Array) {
    if (this.stopped || !this.resampler) return;
    if (!this.options.active()) {
      this.reset();
      return;
    }

    const samples = this.resampler.process(frame);
    // Shift the rolling window left and append.
    const n = Math.min(samples.length, WINDOW);
    this.window.copyWithin(0, n);
    this.window.set(samples.subarray(samples.length - n), WINDOW - n);
    this.filled = Math.min(WINDOW, this.filled + n);
    this.sinceSent += n;

    if (this.filled >= MIN_FRESH && this.sinceSent >= HOP && !this.inFlight) {
      this.sinceSent = 0;
      void this.check(this.window.slice(WINDOW - this.filled));
    }
  }

  private async check(pcm: Int16Array) {
    this.inFlight = true;
    try {
      const res = await apiFetch(`${BASE}/voice/wake`, {
        method: "POST",
        headers: { "Content-Type": "application/octet-stream" },
        body: pcm.buffer as ArrayBuffer,
      });
      if (res.status === 503) {
        this.stop();
        this.options.onError(new WakeWordUnavailable("WAKE WORD UNAVAILABLE"));
        return;
      }
      if (!res.ok) return;
      const { detected } = (await res.json()) as { detected: boolean };
      if (detected && !this.stopped && this.options.active()) {
        this.reset();
        this.options.onWake();
      }
    } catch {
      // Backend briefly unreachable: keep listening, try the next window.
    } finally {
      this.inFlight = false;
    }
  }
}

/**
 * Mic rate (usually 48 kHz) to 16 kHz. Each output sample averages the
 * input samples it spans: a cheap low-pass, enough for speech.
 */
class Resampler {
  private ratio: number;
  private pos = 0; // next output position, in input samples, relative to `carry`
  private carry = new Float32Array(0);

  constructor(inRate: number, outRate: number) {
    this.ratio = inRate / outRate;
  }

  process(input: Float32Array): Int16Array {
    const data = new Float32Array(this.carry.length + input.length);
    data.set(this.carry);
    data.set(input, this.carry.length);

    const out: number[] = [];
    while (this.pos + this.ratio <= data.length) {
      const start = Math.floor(this.pos);
      const end = Math.max(start + 1, Math.floor(this.pos + this.ratio));
      let sum = 0;
      for (let i = start; i < end; i++) sum += data[i];
      const s = Math.max(-1, Math.min(1, sum / (end - start)));
      out.push(Math.round(s * 32767));
      this.pos += this.ratio;
    }

    const used = Math.floor(this.pos);
    this.carry = data.slice(used);
    this.pos -= used;
    return Int16Array.from(out);
  }
}
