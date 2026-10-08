// Push-to-talk: records while held, then the backend's local Whisper
// transcribes it. The mic is open only while recording.
import { JarvisError } from "@/lib/jarvisApi";

import { apiFetch } from "@/lib/auth";

const BASE = "/api/jarvis";

// Shorter presses are treated as accidental taps.
const MIN_RECORDING_MS = 300;

// Hands-free (after the wake word) there's no release, so the recording
// ends on a pause: speech, then this much quiet. Levels are the meter's 0..1.
const SPEECH_LEVEL = 0.2;
const QUIET_LEVEL = 0.1;
const END_PAUSE_MS = 1200;
// Gives up if nothing is said, and caps a long monologue.
const NO_SPEECH_MS = 5000;
const MAX_HANDS_FREE_MS = 20_000;

export interface HandsFree {
  /** The user finished speaking (or never started): call stop(). */
  onEnd(spoke: boolean): void;
}

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
    res = await apiFetch(`${BASE}/voice/transcribe`, {
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
  private timer: ReturnType<typeof setInterval> | undefined;
  private cancelled = false;
  private handsFree: HandsFree | null = null;

  constructor(private onLevel: (level: number) => void) {}

  get recording() {
    return this.recorder !== null;
  }

  /**
   * Opens the mic and starts recording (asks permission the first time).
   * With `handsFree`, it also listens for the end of speech.
   */
  async start(handsFree?: HandsFree): Promise<void> {
    if (this.recorder) return;
    this.cancelled = false;
    this.handsFree = handsFree ?? null;

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
    clearInterval(this.timer);
    this.stream?.getTracks().forEach((t) => t.stop());
    void this.ctx?.close();
    this.ctx = null;
    this.stream = null;
    this.recorder = null;
    this.handsFree = null;
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
    let spoke = false;
    let quietSince = 0;

    const tick = () => {
      analyser.getFloatTimeDomainData(samples);
      let sum = 0;
      for (const s of samples) sum += s * s;
      level += (Math.min(1, Math.sqrt(sum / samples.length) * 6) - level) * 0.35;
      this.onLevel(level);

      const handsFree = this.handsFree;
      if (handsFree) {
        const now = performance.now();
        const elapsed = now - this.startedAt;
        if (level > SPEECH_LEVEL) {
          spoke = true;
          quietSince = 0;
        } else if (spoke && level < QUIET_LEVEL) {
          quietSince ||= now;
        }
        const ended =
          (spoke && quietSince > 0 && now - quietSince >= END_PAUSE_MS)
          || (!spoke && elapsed >= NO_SPEECH_MS)
          || elapsed >= MAX_HANDS_FREE_MS;
        if (ended) {
          this.handsFree = null; // report once
          handsFree.onEnd(spoke);
        }
      }

    };
    // A timer, not animation frames: those stop in a background tab,
    // and a hands-free recording there must still end.
    this.timer = setInterval(tick, 33);
  }
}
