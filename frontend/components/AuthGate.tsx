"use client";

import { createContext, useCallback, useContext, useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { authStatus, login, logout, UNAUTHORIZED_EVENT } from "@/lib/auth";

// "unreachable": the backend didn't answer; the app shows OFFLINE.
type GateState = "checking" | "unreachable" | "open" | "signed-in" | "locked";

interface AuthContextValue {
  /** Signed in with a passcode (so LOCK makes sense). */
  required: boolean;
  /** The backend has no passcode: anyone who can reach it can use it. */
  apiOpen: boolean;
  /** Signs out and shows the passcode screen. */
  lock(): void;
}

const AuthContext = createContext<AuthContextValue>({ required: false, apiOpen: false, lock: () => {} });

export const useAuth = () => useContext(AuthContext);

/**
 * Shows the app once the browser may use the backend, or a passcode
 * screen when it needs to sign in (at start, or when any call gets a 401).
 * While locked the app isn't mounted, so nothing polls or listens.
 */
export default function AuthGate({ children }: { children: ReactNode }) {
  const [state, setState] = useState<GateState>("checking");

  useEffect(() => {
    let cancelled = false;
    void authStatus().then((status) => {
      if (cancelled) return;
      // Unreachable: show the app, which reports OFFLINE; a later 401 locks it.
      if (!status) setState("unreachable");
      else if (!status.required) setState("open");
      else setState(status.authenticated ? "signed-in" : "locked");
    });
    const onUnauthorized = () => setState("locked");
    window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
    return () => {
      cancelled = true;
      window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
    };
  }, []);

  const lock = useCallback(() => {
    void logout().then(() => setState("locked"));
  }, []);

  if (state === "checking") return null;
  if (state === "locked") return <PasscodeScreen onSignedIn={() => setState("signed-in")} />;

  return (
    <AuthContext.Provider value={{ required: state === "signed-in", apiOpen: state === "open", lock }}>
      {children}
    </AuthContext.Provider>
  );
}

function PasscodeScreen({ onSignedIn }: { onSignedIn(): void }) {
  const [passcode, setPasscode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!passcode || busy) return;
    setBusy(true);
    const problem = await login(passcode);
    setBusy(false);
    if (problem) {
      setError(problem);
      setPasscode("");
      inputRef.current?.focus();
    } else {
      onSignedIn();
    }
  }

  return (
    <main className="auth-screen">
      <form className="auth-panel" onSubmit={submit}>
        <h1 className="auth-title">JARVIS</h1>
        <label className="auth-label" htmlFor="passcode">
          ENTER PASSCODE
        </label>
        <input
          id="passcode"
          ref={inputRef}
          className="chat-input auth-input"
          type="password"
          autoComplete="current-password"
          autoFocus
          value={passcode}
          onChange={(e) => setPasscode(e.target.value)}
          disabled={busy}
        />
        <button type="submit" className="hud-btn" disabled={busy || !passcode}>
          {busy ? "…" : "UNLOCK"}
        </button>
        {error && (
          <p className="hud-error" role="alert">
            {error}
          </p>
        )}
      </form>
    </main>
  );
}
