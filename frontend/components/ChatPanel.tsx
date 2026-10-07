"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { chat, getHistory, isOnline, JarvisError } from "@/lib/jarvisApi";
import { MODES, type Mode } from "@/lib/mode";

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
}

export default function ChatPanel({ mode, onThinkingChange, onSend, onReply }: ChatPanelProps) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [pending, setPending] = useState(false);
  const [online, setOnline] = useState<boolean | null>(null);
  const [error, setError] = useState<string | null>(null);

  const logRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const nextId = useRef(0);

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

  async function send(e: FormEvent) {
    e.preventDefault();
    const query = input.trim();
    if (!query || pending) return;

    onSend?.();
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
          placeholder={`Message ${mode === "ultron" ? "Ultron" : "Jarvis"}…  ( / )`}
          aria-label="Message"
          autoComplete="off"
          disabled={pending}
        />
        <button type="submit" className="hud-btn" disabled={pending || !input.trim()}>
          SEND
        </button>
      </form>
    </section>
  );
}
