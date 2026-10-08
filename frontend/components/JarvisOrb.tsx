"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { createOrbScene, type OrbSceneApi } from "@/lib/orbScene";
import { createBrainScene } from "@/lib/brainScene";
import { loadMode, MODES, saveMode, type Mode } from "@/lib/mode";
import { VoicePlayer, voiceStatus } from "@/lib/voice";
import { canRecord } from "@/lib/speech";
import type { RoutineRun, Task } from "@/lib/jarvisApi";
import { HandTracker, type TrackerStatus } from "@/lib/handTracker";
import ChatPanel from "@/components/ChatPanel";
import ReminderCenter from "@/components/ReminderCenter";

type CameraState = "off" | "starting" | "on" | "error";

const MODE_LABEL: Record<TrackerStatus["mode"], string> = {
  idle: "STANDBY",
  spin: "SPIN",
  zoom: "ZOOM",
};

export default function JarvisOrb() {
  const containerRef = useRef<HTMLDivElement>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const overlayRef = useRef<HTMLCanvasElement>(null);
  const sceneRef = useRef<OrbSceneApi | null>(null);
  const trackerRef = useRef<HandTracker | null>(null);

  const [camera, setCamera] = useState<CameraState>("off");
  const [status, setStatus] = useState<TrackerStatus>({ hands: 0, mode: "idle" });
  const [error, setError] = useState<string | null>(null);

  // null until read from storage, so the first scene built is the right one.
  const [mode, setMode] = useState<Mode | null>(null);
  useEffect(() => setMode(loadMode()), []);
  const toggleMode = useCallback(() => {
    voiceRef.current?.stop(); // the other persona shouldn't finish the sentence
    setMode((current) => {
      const next: Mode = current === "ultron" ? "jarvis" : "ultron";
      saveMode(next);
      return next;
    });
  }, []);

  // ——— Voice ———
  // Replies (and reminders) are spoken with the mode's local Piper voice
  // while VOICE is on; the scene pulses with the loudness.
  const voiceRef = useRef<VoicePlayer | null>(null);
  const [voiceModes, setVoiceModes] = useState<Record<Mode, boolean> | null>(null);
  const [voiceOn, setVoiceOn] = useState(false);
  const voiceOnRef = useRef(false);
  const modeRef = useRef<Mode>("jarvis");
  useEffect(() => {
    voiceOnRef.current = voiceOn;
    if (mode) modeRef.current = mode;
  }, [voiceOn, mode]);
  useEffect(() => {
    voiceRef.current = new VoicePlayer((level) => sceneRef.current?.setVoiceLevel(level));
    void voiceStatus().then((status) => {
      setVoiceModes(status.available);
      setWakeSupported(status.wake_word && canRecord());
    });
    try {
      setVoiceOn(localStorage.getItem("jarvis.voice") === "on");
      wakeOnRef.current = localStorage.getItem("jarvis.wake") === "on";
      setWakeOn(wakeOnRef.current);
    } catch {
      // Storage blocked: voice and wake word start off.
    }
    return () => voiceRef.current?.stop();
  }, []);
  const toggleVoice = useCallback(() => {
    const next = !voiceOnRef.current;
    if (next) voiceRef.current?.unlock(); // this click is the user gesture audio needs
    else voiceRef.current?.stop();
    setVoiceOn(next);
    try {
      localStorage.setItem("jarvis.voice", next ? "on" : "off");
    } catch {
      // Not remembered; harmless.
    }
  }, []);

  // ——— Wake word ———
  // While on, the mic stays open and "Hey Jarvis" starts a hands-free
  // recording (ChatPanel listens). Off by default.
  const [wakeSupported, setWakeSupported] = useState(false);
  const [wakeOn, setWakeOn] = useState(false);
  const wakeOnRef = useRef(false);
  const setWake = useCallback((on: boolean) => {
    wakeOnRef.current = on;
    setWakeOn(on);
    try {
      localStorage.setItem("jarvis.wake", on ? "on" : "off");
    } catch {
      // Not remembered; harmless.
    }
  }, []);
  const toggleWake = useCallback(() => setWake(!wakeOnRef.current), [setWake]);
  const isSpeaking = useCallback(() => voiceRef.current?.speaking ?? false, []);
  const onWakeWordFailed = useCallback(() => setWake(false), [setWake]);

  const say = useCallback((text: string, as: Mode) => {
    if (!voiceOnRef.current) return;
    voiceRef.current?.speak(text, as).catch(() => {
      // Interrupted or voice unavailable: the text is on screen anyway.
    });
  }, []);
  const onChatSend = useCallback(() => {
    voiceRef.current?.stop();
    if (voiceOnRef.current) voiceRef.current?.unlock();
  }, []);

  // The orb spins up while Jarvis is thinking or a reminder just fired.
  const busy = useRef({ chat: false, alert: false });
  const alertTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const updateOrb = () => sceneRef.current?.setThinking(busy.current.chat || busy.current.alert);
  const setChatThinking = useCallback((thinking: boolean) => {
    busy.current.chat = thinking;
    updateOrb();
  }, []);
  const flareForReminder = useCallback((tasks: Task[]) => {
    const titles = tasks.map((t) => t.title).join(". ");
    say(`Reminder: ${titles}.`, modeRef.current);
    busy.current.alert = true;
    updateOrb();
    if (alertTimer.current) clearTimeout(alertTimer.current);
    alertTimer.current = setTimeout(() => {
      busy.current.alert = false;
      updateOrb();
    }, 3000);
  }, [say]);
  useEffect(() => () => {
    if (alertTimer.current) clearTimeout(alertTimer.current);
  }, []);
  // A morning briefing / evening review: spoken in the persona that wrote it.
  const deliverBriefing = useCallback((run: RoutineRun) => {
    say(run.text, run.mode);
  }, [say]);

  // Browser notifications need a secure context (localhost or HTTPS).
  const [notifySupported, setNotifySupported] = useState(false);
  const [notifyOn, setNotifyOn] = useState(false);
  useEffect(() => {
    const supported = "Notification" in window && window.isSecureContext;
    setNotifySupported(supported);
    setNotifyOn(supported && Notification.permission === "granted");
  }, []);
  const toggleNotifications = useCallback(async () => {
    if (notifyOn) {
      setNotifyOn(false);
      return;
    }
    const permission = await Notification.requestPermission();
    setNotifyOn(permission === "granted");
  }, [notifyOn]);

  // One scene at a time: switching mode swaps it, keeping the camera
  // (hand tracking) and any "thinking" state.
  useEffect(() => {
    const container = containerRef.current;
    if (!container || !mode) return;
    const scene = mode === "ultron" ? createBrainScene(container) : createOrbScene(container);
    sceneRef.current = scene;
    updateOrb();
    return () => {
      scene.dispose();
      sceneRef.current = null;
    };
    // updateOrb only reads refs, so it isn't a dependency.
  }, [mode]);

  useEffect(
    () => () => {
      trackerRef.current?.stop();
      trackerRef.current = null;
    },
    [],
  );

  const stopGestures = useCallback(() => {
    trackerRef.current?.stop();
    trackerRef.current = null;
    setCamera("off");
    setStatus({ hands: 0, mode: "idle" });
  }, []);

  const startGestures = useCallback(async () => {
    const video = videoRef.current;
    const overlay = overlayRef.current;
    if (!video || !overlay || trackerRef.current) return;

    setCamera("starting");
    setError(null);

    const tracker = new HandTracker(video, overlay, {
      onRotate: (dt, dp) => sceneRef.current?.rotateBy(dt, dp),
      onZoom: (factor) => sceneRef.current?.zoomBy(factor),
      onStatus: setStatus,
    });
    trackerRef.current = tracker;

    try {
      await tracker.start();
      // Stopped (G pressed again) while starting: stopGestures already reset state.
      if (trackerRef.current !== tracker) return;
      setCamera("on");
    } catch (err) {
      if (trackerRef.current !== tracker) return;
      trackerRef.current = null;
      tracker.stop();
      setCamera("error");
      setError(
        err instanceof DOMException && err.name === "NotAllowedError"
          ? "CAMERA ACCESS DENIED"
          : "TRACKING INIT FAILED",
      );
    }
  }, []);

  const toggleGestures = useCallback(() => {
    if (trackerRef.current) stopGestures();
    else void startGestures();
  }, [startGestures, stopGestures]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      // Typing in the chat (or Cmd/Ctrl shortcuts) shouldn't drive the orb.
      const target = e.target as HTMLElement | null;
      if (target?.closest("input, textarea, [contenteditable]")) return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      switch (e.key) {
        case "+":
        case "=":
          sceneRef.current?.zoomIn();
          break;
        case "-":
        case "_":
          sceneRef.current?.zoomOut();
          break;
        case "r":
        case "R":
          sceneRef.current?.resetView();
          break;
        case "g":
        case "G":
          toggleGestures();
          break;
        case "m":
        case "M":
          toggleMode();
          break;
        case "v":
        case "V":
          toggleVoice();
          break;
        case "w":
        case "W":
          if (wakeSupported) toggleWake();
          break;
        case "Escape":
          voiceRef.current?.stop();
          break;
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [toggleGestures, toggleMode, toggleVoice, toggleWake, wakeSupported]);

  const cameraOn = camera === "on";

  return (
    <>
      {/* React 19 hoists this into <head>; it follows the mode. */}
      <title>{mode === "ultron" ? "Ultron" : "Jarvis"}</title>
      <div ref={containerRef} className="orb-root" />

      <div className="overlay-vignette" />
      <div className="overlay-grain" />
      <div className="overlay-scanlines" />

      <div className="hud hud-title">{mode ? MODES[mode].title : "\u00a0"}</div>

      <ChatPanel
        mode={mode ?? "jarvis"}
        onThinkingChange={setChatThinking}
        onSend={onChatSend}
        onReply={say}
        onListenLevel={(level) => sceneRef.current?.setVoiceLevel(level)}
        wakeWord={wakeSupported && wakeOn}
        isSpeaking={isSpeaking}
        onWakeWordFailed={onWakeWordFailed}
      />

      <ReminderCenter onAlert={flareForReminder} onBriefing={deliverBriefing} notify={notifyOn} />

      <div className="hud hud-hint">
        <div>
          <span className="key">DRAG</span> spin&nbsp;&nbsp;
          <span className="key">SCROLL</span> zoom
        </div>
        {cameraOn ? (
          <div>
            <span className="key">PINCH + MOVE</span> spin&nbsp;&nbsp;
            <span className="key">PINCH BOTH HANDS ± SPREAD</span> zoom
          </div>
        ) : (
          <div>
            <span className="key">G</span> hand gestures&nbsp;&nbsp;
            <span className="key">R</span> reset&nbsp;&nbsp;
            <span className="key">+/−</span> zoom&nbsp;&nbsp;
            <span className="key">/</span> chat&nbsp;&nbsp;
            <span className="key">M</span> mode&nbsp;&nbsp;
            <span className="key">V</span> voice&nbsp;&nbsp;
            <span className="key">SPACE</span> hold to talk
            {wakeSupported && (
              <>
                &nbsp;&nbsp;<span className="key">W</span> wake word
              </>
            )}
          </div>
        )}
      </div>

      <div className="hud hud-controls">
        <div className={`camera-panel${cameraOn ? " visible" : ""}`}>
          {/* Mirrored preview so it behaves like a mirror */}
          <video ref={videoRef} muted playsInline className="camera-video" />
          <canvas ref={overlayRef} width={208} height={156} className="camera-overlay" />
          <div className="camera-status">
            {status.hands > 0
              ? `${status.hands} HAND${status.hands > 1 ? "S" : ""} · ${MODE_LABEL[status.mode]}`
              : "SHOW HANDS"}
          </div>
        </div>

        {error && <div className="hud-error">{error}</div>}

        <div className="hud-row">
          <button
            type="button"
            className={`hud-btn hud-mode${mode === "ultron" ? " hud-mode-ultron" : ""}`}
            onClick={toggleMode}
            disabled={!mode}
            title="Switch between JARVIS and ULTRON (M)"
          >
            {mode ? MODES[mode].name : "…"}
          </button>
          {voiceModes && (voiceModes.jarvis || voiceModes.ultron) && (
            <button
              type="button"
              className="hud-btn"
              aria-pressed={voiceOn}
              onClick={toggleVoice}
              disabled={!!mode && !voiceModes[mode]}
              title={
                mode && !voiceModes[mode]
                  ? `No voice installed for ${MODES[mode].name}`
                  : "Speak replies and reminders (V; Esc stops)"
              }
            >
              {voiceOn ? "VOICE ON" : "VOICE OFF"}
            </button>
          )}
          {wakeSupported && (
            <button
              type="button"
              className="hud-btn"
              aria-pressed={wakeOn}
              onClick={toggleWake}
              title='Listen for "Hey Jarvis" (W). The mic stays open while on; audio is checked locally and not kept.'
            >
              {wakeOn ? "WAKE ON" : "WAKE OFF"}
            </button>
          )}
        </div>
        <div className="hud-row">
          {notifySupported && (
            <button
              type="button"
              className="hud-btn"
              aria-pressed={notifyOn}
              onClick={() => void toggleNotifications()}
              title="Browser notifications for reminders while this tab is in the background"
            >
              {notifyOn ? "ALERTS ON" : "ALERTS OFF"}
            </button>
          )}
          <button
            type="button"
            className="hud-btn"
            aria-pressed={cameraOn}
            onClick={toggleGestures}
            disabled={camera === "starting"}
          >
            {camera === "starting" ? "INITIALIZING…" : cameraOn ? "GESTURES ON" : "GESTURES OFF"}
          </button>
        </div>
        <div className="hud-row">
          <button type="button" className="hud-btn" onClick={() => sceneRef.current?.zoomIn()} aria-label="Zoom in">
            +
          </button>
          <button type="button" className="hud-btn" onClick={() => sceneRef.current?.zoomOut()} aria-label="Zoom out">
            −
          </button>
          <button type="button" className="hud-btn" onClick={() => sceneRef.current?.resetView()}>
            RESET
          </button>
        </div>
      </div>
    </>
  );
}
