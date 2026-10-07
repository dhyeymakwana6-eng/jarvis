"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { chat, isOnline, JarvisError } from "@/lib/jarvisApi";

interface Message {
  id: number;
  role: "user" | "jarvis";
  text: string;
}

interface ChatPanelProps {
  /** Called when a request starts/finishes, to animate the orb. */
  onThinkingChange(thinking: boolean): void;
}

export default function ChatPanel({ onThinkingChange }: ChatPanelProps) {
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
    void isOnline().then((ok) => {
      if (!cancelled) setOnline(ok);
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

    setInput("");
    setError(null);
    addMessage("user", query);
    setPending(true);
    onThinkingChange(true);

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const reply = await chat(query, controller.signal);
      addMessage("jarvis", reply);
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
    <section className="hud hud-chat" aria-label="Chat with Jarvis">
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
            <span className="chat-role">{m.role === "user" ? "YOU" : "JARVIS"}</span>
            <p>{m.text}</p>
          </div>
        ))}
        {pending && (
          <div className="chat-msg chat-msg-jarvis">
            <span className="chat-role">JARVIS</span>
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
          placeholder="Message Jarvis…  ( / )"
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
