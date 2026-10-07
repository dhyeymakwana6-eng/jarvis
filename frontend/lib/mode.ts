// The two personas. Each has its own scene and, on the backend, its
// own personality; later its own voice.
export type Mode = "jarvis" | "ultron";

export const MODES: Record<Mode, { name: string; title: string }> = {
  jarvis: { name: "JARVIS", title: "J.A.R.V.I.S." },
  ultron: { name: "ULTRON", title: "U.L.T.R.O.N." },
};

const STORAGE_KEY = "jarvis.mode";

/** The mode this device used last (a per-device preference). */
export function loadMode(): Mode {
  try {
    return localStorage.getItem(STORAGE_KEY) === "ultron" ? "ultron" : "jarvis";
  } catch {
    return "jarvis"; // storage blocked (private mode etc.)
  }
}

export function saveMode(mode: Mode) {
  try {
    localStorage.setItem(STORAGE_KEY, mode);
  } catch {
    // Not remembered; harmless.
  }
}
