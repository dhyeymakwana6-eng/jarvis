"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  completeTask,
  dismissReminder,
  dismissRoutine,
  getDueReminders,
  getDueRoutines,
  snoozeReminder,
  type RoutineRun,
  type Task,
} from "@/lib/jarvisApi";

const ROUTINE_TITLE: Record<RoutineRun["kind"], string> = {
  morning: "MORNING BRIEFING",
  evening: "EVENING REVIEW",
};

const POLL_MS = 30_000;
const SNOOZE_MINUTES = 10;

interface ReminderCenterProps {
  /** Called with newly arrived reminders, to flare the orb and speak them. */
  onAlert(tasks: Task[]): void;
  /** Called with a newly arrived briefing/review, e.g. to speak it. */
  onBriefing?(run: RoutineRun): void;
  /** Browser notifications are shown only while the tab is hidden. */
  notify: boolean;
}

function formatTime(iso: string | null): string | null {
  if (!iso) return null;
  const date = new Date(iso);
  const sameDay = date.toDateString() === new Date().toDateString();
  return sameDay
    ? date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
    : date.toLocaleString([], { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

export default function ReminderCenter({ onAlert, onBriefing, notify }: ReminderCenterProps) {
  const [reminders, setReminders] = useState<Task[]>([]);
  const [briefings, setBriefings] = useState<RoutineRun[]>([]);
  // Briefing versions already announced (a rerun rewrites the same id).
  const seenBriefings = useRef(new Set<string>());
  const onBriefingRef = useRef(onBriefing);
  useEffect(() => {
    onBriefingRef.current = onBriefing;
  }, [onBriefing]);
  const [busy, setBusy] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Reminders already announced, so polling doesn't re-alert.
  const seen = useRef(new Set<number>());
  const notifyRef = useRef(notify);
  const onAlertRef = useRef(onAlert);
  useEffect(() => {
    notifyRef.current = notify;
    onAlertRef.current = onAlert;
  }, [notify, onAlert]);

  const pollRoutines = useCallback(async () => {
    let due: RoutineRun[];
    try {
      due = await getDueRoutines();
    } catch {
      return;
    }
    for (const run of due) {
      const key = `${run.id}@${run.updated_at}`;
      if (seenBriefings.current.has(key)) continue;
      seenBriefings.current.add(key);
      onBriefingRef.current?.(run);
      if (notifyRef.current && document.hidden && "Notification" in window) {
        new Notification(run.kind === "morning" ? "Morning briefing" : "Evening review", {
          body: run.text,
          tag: `jarvis-routine-${run.id}`,
        });
      }
    }
    setBriefings(due);
  }, []);

  const poll = useCallback(async () => {
    void pollRoutines();
    let due: Task[];
    try {
      due = await getDueReminders();
    } catch {
      return; // Backend offline: the chat panel already says so.
    }

    const fresh = due.filter((t) => !seen.current.has(t.id));
    fresh.forEach((t) => seen.current.add(t.id));

    if (fresh.length > 0) {
      onAlertRef.current(fresh);
      if (notifyRef.current && document.hidden && "Notification" in window) {
        for (const t of fresh) {
          new Notification("Jarvis reminder", {
            body: t.title,
            tag: `jarvis-reminder-${t.id}`,
          });
        }
      }
    }

    setReminders(due);
  }, [pollRoutines]);

  useEffect(() => {
    void poll();
    const timer = setInterval(() => void poll(), POLL_MS);
    const onVisible = () => {
      if (!document.hidden) void poll();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [poll]);

  async function act(task: Task, action: (id: number) => Promise<void>) {
    setBusy(task.id);
    setError(null);
    try {
      await action(task.id);
      setReminders((prev) => prev.filter((t) => t.id !== task.id));
      // Snoozed reminders come back later and should alert again.
      seen.current.delete(task.id);
    } catch {
      setError("COULDN'T UPDATE REMINDER");
    } finally {
      setBusy(null);
    }
  }

  async function dismissBriefing(run: RoutineRun) {
    setError(null);
    try {
      await dismissRoutine(run.id);
      setBriefings((prev) => prev.filter((r) => r.id !== run.id));
    } catch {
      setError("COULDN'T DISMISS BRIEFING");
    }
  }

  if (reminders.length === 0 && briefings.length === 0 && !error) return null;

  return (
    <section className="hud hud-reminders" aria-label="Reminders" aria-live="assertive">
      {briefings.map((run) => (
        <article key={run.id} className="reminder-card reminder-briefing">
          <header className="reminder-label">
            <span>{ROUTINE_TITLE[run.kind]}</span>
          </header>
          <p className="reminder-briefing-text">{run.text}</p>
          <div className="reminder-actions">
            <button type="button" className="hud-btn" onClick={() => void dismissBriefing(run)}>
              DISMISS
            </button>
          </div>
        </article>
      ))}
      {reminders.map((task) => {
        const due = formatTime(task.due_at);
        const at = formatTime(task.remind_at);
        return (
          <article key={task.id} className={`reminder-card${task.priority === "high" ? " reminder-high" : ""}`}>
            <header className="reminder-label">
              <span>REMINDER</span>
              {at && <span>{at}</span>}
            </header>
            <p className="reminder-title">{task.title}</p>
            {due && <p className="reminder-due">DUE {due}</p>}
            <div className="reminder-actions">
              <button type="button" className="hud-btn" disabled={busy === task.id} onClick={() => act(task, completeTask)}>
                DONE
              </button>
              <button
                type="button"
                className="hud-btn"
                disabled={busy === task.id}
                onClick={() => act(task, (id) => snoozeReminder(id, SNOOZE_MINUTES))}
              >
                +{SNOOZE_MINUTES}M
              </button>
              <button type="button" className="hud-btn" disabled={busy === task.id} onClick={() => act(task, dismissReminder)}>
                DISMISS
              </button>
            </div>
          </article>
        );
      })}
      {error && <div className="hud-error">{error}</div>}
    </section>
  );
}
