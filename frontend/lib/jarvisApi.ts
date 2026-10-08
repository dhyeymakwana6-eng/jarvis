// Client for the Jarvis backend, via the /api/jarvis proxy in next.config.ts.
import type { Mode } from "@/lib/mode";

import { apiFetch } from "@/lib/auth";

const BASE = "/api/jarvis";

export class JarvisError extends Error {}

async function detail(res: Response): Promise<string> {
  try {
    const body = await res.json();
    if (typeof body?.detail === "string") return body.detail;
  } catch {
    // Not JSON (e.g. the proxy's own error page).
  }
  return `${res.status} ${res.statusText}`;
}

/** True if the backend answers its health check. */
export async function isOnline(): Promise<boolean> {
  try {
    const res = await apiFetch(BASE, { cache: "no-store" });
    return res.ok;
  } catch {
    return false;
  }
}

/** Sends one message; the persona answers using memories, profile, goals and tasks. */
/** Something the assistant did (or wants to do) to a task, project or goal. */
export interface Action {
  tool: string;
  summary: string;
  // "pending" waits for the user's confirmation (e.g. deleting a task).
  status: "done" | "failed" | "pending" | "declined" | "expired";
  pending_id: string | null;
  // The existing item changed or deleted.
  target_id: number | null;
}

export interface ChatReply {
  response: string;
  actions: Action[];
}

export async function chat(query: string, mode: Mode, signal?: AbortSignal): Promise<ChatReply> {
  let res: Response;
  try {
    res = await apiFetch(`${BASE}/memory/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query, mode }),
      signal,
    });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") throw err;
    throw new JarvisError("BACKEND UNREACHABLE");
  }

  if (res.status === 503) throw new JarvisError("LLM OFFLINE — IS OLLAMA RUNNING?");
  if (res.status === 500 || res.status === 502) {
    // The proxy answers 500 when the backend itself is down.
    throw new JarvisError(`BACKEND ERROR: ${await detail(res)}`);
  }
  if (!res.ok) throw new JarvisError(await detail(res));

  return (await res.json()) as ChatReply;
}

/** Confirms or declines an action that's waiting; returns the outcome. */
export async function resolveAction(pendingId: string, approve: boolean): Promise<Action> {
  let res: Response;
  try {
    res = await apiFetch(`${BASE}/memory/chat/actions/${encodeURIComponent(pendingId)}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ approve }),
    });
  } catch {
    throw new JarvisError("BACKEND UNREACHABLE");
  }
  if (!res.ok) throw new JarvisError(await detail(res));
  return (await res.json()) as Action;
}

export interface ChatTurn {
  id: number;
  user_message: string;
  assistant_message: string;
  mode: Mode;
  actions: Action[] | null;
  created_at: string;
}

/**
 * The current chat session (turns since the last 30 min of silence),
 * oldest first — the same turns Jarvis sees as context.
 */
export async function getHistory(): Promise<ChatTurn[]> {
  const res = await apiFetch(`${BASE}/memory/chat/history`, { cache: "no-store" });
  if (!res.ok) throw new JarvisError(await detail(res));
  return (await res.json()) as ChatTurn[];
}

export interface Task {
  id: number;
  title: string;
  notes: string | null;
  priority: "low" | "normal" | "high";
  due_at: string | null;
  remind_at: string | null;
}

async function post(path: string, body?: unknown, method = "POST"): Promise<void> {
  const res = await apiFetch(`${BASE}${path}`, {
    method,
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  // 404: another device already handled it — nothing left to do.
  if (!res.ok && res.status !== 404) throw new JarvisError(await detail(res));
}

/** Reminders whose time has passed and that no device has handled yet. */
export async function getDueReminders(): Promise<Task[]> {
  const res = await apiFetch(`${BASE}/reminders/due`, { cache: "no-store" });
  if (!res.ok) throw new JarvisError(await detail(res));
  return (await res.json()) as Task[];
}

export const dismissReminder = (id: number) => post(`/reminders/${id}/dismiss`);

export const snoozeReminder = (id: number, minutes: number) =>
  post(`/reminders/${id}/snooze`, { minutes });

export const completeTask = (id: number) => post(`/tasks/${id}`, { status: "done" }, "PATCH");

/** A scheduled routine's text: the morning briefing or evening review. */
export interface RoutineRun {
  id: number;
  kind: "morning" | "evening";
  run_date: string;
  text: string;
  /** Persona it was written in (and should be spoken in). */
  mode: Mode;
  created_at: string;
  updated_at: string;
}

/** Today's routines that no device has dismissed yet. */
export async function getDueRoutines(): Promise<RoutineRun[]> {
  const res = await apiFetch(`${BASE}/routines/due`, { cache: "no-store" });
  if (!res.ok) throw new JarvisError(await detail(res));
  return (await res.json()) as RoutineRun[];
}

export const dismissRoutine = (id: number) => post(`/routines/runs/${id}/dismiss`);
