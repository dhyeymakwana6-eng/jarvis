"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { chat, getHistory, isOnline, JarvisError } from "@/lib/jarvisApi";
import { MODES, type Mode } from "@/lib/mode";
import { canRecord, Recorder, transcribe } from "@/lib/speech";
import { WakeListener } from "@/lib/wake";

type MicState = "idle" | "listening" | "transcribing";

interface Message {
  id: number;
  // Assistant replies are labelled with the persona that gave them.
  role: "user" | Mode;
  text: string;
}

interface ChatPanelProps {
  /** Persona that answers: picks the backend personality. */
  mode: Mode;
  /** Called when a request starts/finishes, to animate the orb. */
  onThinkingChange(thinking: boolean): void;
  /** Called synchronously on send (a user gesture), e.g. to unlock audio. */
  onSend?(): void;
  /** Called with each reply, e.g. to speak it. */
  onReply?(text: string, mode: Mode): void;
  /** Mic loudness 0..1 while the user is talking, for the scene. */
  onListenLevel?(level: number): void;
  /** Listen for "Hey Jarvis", then record hands-free. */
  wakeWord?: boolean;
  /** Replies are being spoken (the wake word pauses meanwhile). */
  isSpeaking?(): boolean;
  /** The wake word stopped working (e.g. models missing, mic blocked). */
  onWakeWordFailed?(): void;
}

export default function ChatPanel({
  mode, onThinkingChange, onSend, onReply, onListenLevel, wakeWord = false, isSpeaking, onWakeWordFailed,
}: ChatPanelProps) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [pending, setPending] = useState(false);
  const [online, setOnline] = useState<boolean | null>(null);
  const [error, setError] = useState<string | null>(null);

  const logRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const nextId = useRef(0);
  const pendingRef = useRef(false);
  useEffect(() => {
    pendingRef.current = pending;
  }, [pending]);

  useEffect(() => {
    let cancelled = false;
    // Restore the current session, so the panel shows what Jarvis
    // will treat as context (also across reloads and devices).
    getHistory()
      .then((turns) => {
        if (cancelled) return;
        setOnline(true);
        setMessages((prev) =>
          prev.length > 0
            ? prev
            : turns.flatMap((t) => [
                { id: nextId.current++, role: "user" as const, text: t.user_message },
                { id: nextId.current++, role: t.mode, text: t.assistant_message },
              ]),
        );
      })
      .catch(async () => {
        if (!cancelled) setOnline(await isOnline());
      });
    return () => {
      cancelled = true;
      abortRef.current?.abort();
    };
  }, []);

  useEffect(() => {
    logRef.current?.scrollTo({ top: logRef.current.scrollHeight });
  }, [messages, pending]);

  // "/" focuses the input, like a search box.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "/" || e.target instanceof HTMLInputElement) return;
      e.preventDefault();
      inputRef.current?.focus();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const addMessage = (role: Message["role"], text: string) =>
    setMessages((prev) => [...prev, { id: nextId.current++, role, text }]);

  function send(e: FormEvent) {
    e.preventDefault();
    onSend?.();
    void sendText(input);
  }

  async function sendText(text: string) {
    const query = text.trim();
    if (!query || pending) return;

    setInput("");
    setError(null);
    addMessage("user", query);
    setPending(true);
    onThinkingChange(true);

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const reply = await chat(query, mode, controller.signal);
      addMessage(mode, reply);
      onReply?.(reply, mode);
      setOnline(true);
    } catch (err) {
      if (controller.signal.aborted) return;
      setError(err instanceof JarvisError ? err.message : "REQUEST FAILED");
      setOnline(await isOnline());
    } finally {
      if (!controller.signal.aborted) {
        setPending(false);
        onThinkingChange(false);
        inputRef.current?.focus();
      }
    }
  }

  // ——— Push to talk ———
  // Hold TALK (or Space when not typing), speak, release: the recording
  // is transcribed locally and sent like a typed message.
  const [mic, setMic] = useState<MicState>("idle");
  const [micSupported, setMicSupported] = useState(false);
  const recorderRef = useRef<Recorder | null>(null);
  const listenLevel = useRef(onListenLevel);
  const sendTextRef = useRef(sendText);
  useEffect(() => {
    listenLevel.current = onListenLevel;
    sendTextRef.current = sendText;
  });
  useEffect(() => {
    setMicSupported(canRecord());
    recorderRef.current = new Recorder((level) => listenLevel.current?.(level));
    return () => void recorderRef.current?.stop();
  }, []);

  const [handsFree, setHandsFree] = useState(false);
  const micRef = useRef<MicState>("idle");
  const updateMic = (state: MicState) => {
    micRef.current = state;
    setMic(state);
  };

  // Hands-free (after the wake word) it stops by itself on a pause.
  async function startTalking(wake = false) {
    if (micRef.current !== "idle" || pending) return;
    onSend?.(); // stops speech, unlocks audio (a user gesture when pressed)
    setError(null);
    setHandsFree(wake);
    updateMic("listening");
    try {
      await recorderRef.current?.start(
        wake
          ? { onEnd: (spoke) => void (spoke ? stopRef.current() : cancelRef.current()) }
          : undefined,
      );
    } catch {
      updateMic("idle");
      setError("MICROPHONE BLOCKED");
    }
  }

  // Woken but nothing was said: drop it quietly.
  async function cancelTalking() {
    if (micRef.current !== "listening") return;
    await recorderRef.current?.stop();
    updateMic("idle");
  }

  async function stopTalking() {
    if (micRef.current !== "listening") return;
    const audio = await recorderRef.current?.stop();
    if (!audio) {
      updateMic("idle"); // a tap, not speech
      return;
    }
    updateMic("transcribing");
    try {
      const text = await transcribe(audio);
      updateMic("idle");
      if (text) void sendTextRef.current(text);
      else setError("DIDN'T CATCH THAT");
    } catch (err) {
      updateMic("idle");
      setError(err instanceof JarvisError ? err.message : "COULDN'T HEAR THAT");
    }
  }
  const startRef = useRef(startTalking);
  const stopRef = useRef(stopTalking);
  const cancelRef = useRef(cancelTalking);
  useEffect(() => {
    startRef.current = startTalking;
    stopRef.current = stopTalking;
    cancelRef.current = cancelTalking;
  });

  // ——— Wake word ———
  // "Hey Jarvis" starts a hands-free recording. Paused while recording,
  // waiting for a reply or speaking one.
  const isSpeakingRef = useRef(isSpeaking);
  const wakeFailedRef = useRef(onWakeWordFailed);
  useEffect(() => {
    isSpeakingRef.current = isSpeaking;
    wakeFailedRef.current = onWakeWordFailed;
  });
  useEffect(() => {
    if (!wakeWord || !micSupported) return;
    const listener = new WakeListener({
      active: () => micRef.current === "idle" && !pendingRef.current && !isSpeakingRef.current?.(),
      onWake: () => {
        listener.chime();
        void startRef.current(true);
      },
      onError: (err) => {
        setError(err.message);
        wakeFailedRef.current?.();
      },
    });
    listener.start().catch(() => {
      listener.stop();
      setError("MICROPHONE BLOCKED");
      wakeFailedRef.current?.();
    });
    return () => listener.stop();
  }, [wakeWord, micSupported]);

  // Space: hold to talk, unless typing or on a button.
  useEffect(() => {
    if (!micSupported) return;
    const typing = (target: EventTarget | null) =>
      target instanceof HTMLElement && !!target.closest("input, textarea, button, [contenteditable]");
    const down = (e: KeyboardEvent) => {
      if (e.code !== "Space" || e.repeat || typing(e.target)) return;
      e.preventDefault();
      void startRef.current();
    };
    const up = (e: KeyboardEvent) => {
      if (e.code !== "Space" || typing(e.target)) return;
      e.preventDefault();
      void stopRef.current();
    };
    window.addEventListener("keydown", down);
    window.addEventListener("keyup", up);
    return () => {
      window.removeEventListener("keydown", down);
      window.removeEventListener("keyup", up);
    };
  }, [micSupported]);

  const placeholder =
    mic === "listening" ? (handsFree ? "LISTENING…  (pause to send)" : "LISTENING…  (release to send)")
    : mic === "transcribing" ? "TRANSCRIBING…"
    : `Message ${mode === "ultron" ? "Ultron" : "Jarvis"}…  ( / )${wakeWord ? "  or say “Hey Jarvis”" : ""}`;

  const statusLabel = online === null ? "CONNECTING…" : online ? "ONLINE" : "OFFLINE";

  return (
    <section className="hud hud-chat" aria-label={`Chat with ${MODES[mode].name}`}>
      <header className="chat-header">
        <span>COMMS</span>
        <span className={`chat-status chat-status-${online === false ? "off" : "on"}`}>
          {statusLabel}
        </span>
      </header>

      <div ref={logRef} className="chat-log" aria-live="polite">
        {messages.length === 0 && !pending && (
          <p className="chat-empty">
            Tell me about yourself, your projects or your goals — I&apos;ll remember.
          </p>
        )}
        {messages.map((m) => (
          <div key={m.id} className={`chat-msg chat-msg-${m.role}`}>
            <span className="chat-role">{m.role === "user" ? "YOU" : MODES[m.role].name}</span>
            <p>{m.text}</p>
          </div>
        ))}
        {pending && (
          <div className={`chat-msg chat-msg-${mode}`}>
            <span className="chat-role">{MODES[mode].name}</span>
            <p className="chat-thinking">PROCESSING…</p>
          </div>
        )}
      </div>

      {error && <div className="hud-error chat-error">{error}</div>}

      <form className="chat-form" onSubmit={send}>
        <input
          ref={inputRef}
          className="chat-input"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder={placeholder}
          aria-label="Message"
          autoComplete="off"
          disabled={pending || mic !== "idle"}
        />
        {micSupported && !input.trim() ? (
          <button
            type="button"
            className={`hud-btn chat-talk${mic === "listening" ? " chat-talk-live" : ""}`}
            aria-pressed={mic === "listening"}
            disabled={pending || mic === "transcribing"}
            title="Hold to talk (or hold Space)"
            onPointerDown={(e) => {
              e.currentTarget.setPointerCapture(e.pointerId);
              void startTalking();
            }}
            onPointerUp={() => void stopTalking()}
            onPointerCancel={() => void stopTalking()}
            onContextMenu={(e) => e.preventDefault()}
          >
            {mic === "listening" ? "● REC" : mic === "transcribing" ? "…" : "TALK"}
          </button>
        ) : (
          <button type="submit" className="hud-btn" disabled={pending || !input.trim()}>
            SEND
          </button>
        )}
      </form>
    </section>
  );
}
