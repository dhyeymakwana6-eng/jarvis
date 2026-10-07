// Client for the Jarvis backend, via the /api/jarvis proxy in next.config.ts.
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
    const res = await fetch(BASE, { cache: "no-store" });
    return res.ok;
  } catch {
    return false;
  }
}

/** Sends one message; Jarvis answers using its memories, profile and goals. */
export async function chat(query: string, signal?: AbortSignal): Promise<string> {
  let res: Response;
  try {
    res = await fetch(`${BASE}/memory/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query }),
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

  const body = (await res.json()) as { response: string };
  return body.response;
}

export interface ChatTurn {
  id: number;
  user_message: string;
  assistant_message: string;
  created_at: string;
}

/**
 * The current chat session (turns since the last 30 min of silence),
 * oldest first — the same turns Jarvis sees as context.
 */
export async function getHistory(): Promise<ChatTurn[]> {
  const res = await fetch(`${BASE}/memory/chat/history`, { cache: "no-store" });
  if (!res.ok) throw new JarvisError(await detail(res));
  return (await res.json()) as ChatTurn[];
}
