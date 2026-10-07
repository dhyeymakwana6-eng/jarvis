// Push-to-talk: records while held, then the backend's local Whisper
// transcribes it. The mic is open only while recording.
import { JarvisError } from "@/lib/jarvisApi";

const BASE = "/api/jarvis";

// Shorter presses are treated as accidental taps.
const MIN_RECORDING_MS = 300;

/** The browser can record (mic access needs localhost or HTTPS). */
export function canRecord(): boolean {
  return typeof window !== "undefined"
    && window.isSecureContext
    && !!navigator.mediaDevices?.getUserMedia
    && typeof MediaRecorder !== "undefined";
}

export async function transcribe(audio: Blob): Promise<string> {
  let res: Response;
  try {
    res = await fetch(`${BASE}/voice/transcribe`, {
      method: "POST",
      headers: { "Content-Type": audio.type || "application/octet-stream" },
      body: audio,
    });
  } catch {
    throw new JarvisError("BACKEND UNREACHABLE");
  }
  if (res.status === 503) throw new JarvisError("SPEECH MODEL UNAVAILABLE");
  if (!res.ok) throw new JarvisError("COULDN'T HEAR THAT");
  return ((await res.json()) as { text: string }).text;
}

export class Recorder {
  private stream: MediaStream | null = null;
  private recorder: MediaRecorder | null = null;
  private chunks: Blob[] = [];
  private startedAt = 0;
  private ctx: AudioContext | null = null;
  private rafId = 0;
  private cancelled = false;

  constructor(private onLevel: (level: number) => void) {}

  get recording() {
    return this.recorder !== null;
  }

  /** Opens the mic and starts recording (asks permission the first time). */
  async start(): Promise<void> {
    if (this.recorder) return;
    this.cancelled = false;

    const stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    });
    // Released before the mic opened (a quick tap): close it again.
    if (this.cancelled) {
      stream.getTracks().forEach((t) => t.stop());
      return;
    }

    this.stream = stream;
    this.chunks = [];
    const recorder = new MediaRecorder(stream);
    recorder.ondataavailable = (e) => {
      if (e.data.size > 0) this.chunks.push(e.data);
    };
    recorder.start();
    this.recorder = recorder;
    this.startedAt = performance.now();
    this.meter(stream);
  }

  /** Stops and returns the recording, or null if it was too short. */
  async stop(): Promise<Blob | null> {
    this.cancelled = true;
    const recorder = this.recorder;
    if (!recorder) return null;

    const duration = performance.now() - this.startedAt;
    const stopped = new Promise<void>((resolve) => (recorder.onstop = () => resolve()));
    recorder.stop();
    await stopped;

    this.release();

    if (duration < MIN_RECORDING_MS) return null;
    return new Blob(this.chunks, { type: recorder.mimeType });
  }

  private release() {
    cancelAnimationFrame(this.rafId);
    this.stream?.getTracks().forEach((t) => t.stop());
    void this.ctx?.close();
    this.ctx = null;
    this.stream = null;
    this.recorder = null;
    this.onLevel(0);
  }

  /** Mic loudness 0..1 while recording, so the scene reacts to the user. */
  private meter(stream: MediaStream) {
    this.ctx = new AudioContext();
    const analyser = this.ctx.createAnalyser();
    analyser.fftSize = 512;
    this.ctx.createMediaStreamSource(stream).connect(analyser);
    const samples = new Float32Array(analyser.fftSize);
    let level = 0;

    const tick = () => {
      analyser.getFloatTimeDomainData(samples);
      let sum = 0;
      for (const s of samples) sum += s * s;
      level += (Math.min(1, Math.sqrt(sum / samples.length) * 6) - level) * 0.35;
      this.onLevel(level);
      this.rafId = requestAnimationFrame(tick);
    };
    tick();
  }
}
