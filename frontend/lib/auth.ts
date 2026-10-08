// Sign-in for the backend. When it has a passcode (JARVIS_PASSCODE), it
// answers 401 until the browser has a session cookie from /auth/login;
// apiFetch reports that so the app can show the passcode screen.

const BASE = "/api/jarvis";

export const UNAUTHORIZED_EVENT = "jarvis:unauthorized";

/** fetch for backend calls: announces a 401 (session missing or expired). */
export async function apiFetch(input: string, init?: RequestInit): Promise<Response> {
  const res = await fetch(input, init);
  if (res.status === 401) window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
  return res;
}

export interface AuthStatus {
  /** A passcode is set on the backend. */
  required: boolean;
  /** This browser may use the API. */
  authenticated: boolean;
}

/** null when the backend can't be reached. */
export async function authStatus(): Promise<AuthStatus | null> {
  try {
    const res = await fetch(`${BASE}/auth/status`, { cache: "no-store" });
    return res.ok ? ((await res.json()) as AuthStatus) : null;
  } catch {
    return null;
  }
}

/** Signs in; returns an error message, or null on success. */
export async function login(passcode: string): Promise<string | null> {
  let res: Response;
  try {
    res = await fetch(`${BASE}/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ passcode }),
    });
  } catch {
    return "BACKEND UNREACHABLE";
  }
  if (res.ok) return null;
  if (res.status === 401) return "WRONG PASSCODE";
  if (res.status === 429) return `TOO MANY ATTEMPTS — WAIT ${res.headers.get("retry-after") ?? "A FEW"}S`;
  return "SIGN-IN FAILED";
}

export async function logout(): Promise<void> {
  try {
    await fetch(`${BASE}/auth/logout`, { method: "POST" });
  } catch {
    // Offline: the cookie stays, but the app still locks.
  }
}
