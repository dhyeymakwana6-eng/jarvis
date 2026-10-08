# Jarvis (Project D.0)

A local-first personal AI assistant with long-term memory: it remembers
what you tell it, builds a profile of you, and tracks your projects and
goals. Everything runs on your machine (PostgreSQL + Ollama).

```
frontend/  Next.js + Three.js holographic orb with a chat panel
backend/   FastAPI memory, profile and tracking API
docs/      architecture, roadmap, vision
```

The browser only talks to the frontend; it proxies `/api/jarvis/*` to
the backend (see `frontend/next.config.ts`), so the backend needs no
CORS setup and can stay bound to localhost.

## Setup

Requirements: Python 3.12+, Node 20+, PostgreSQL with the `vector`
(pgvector) extension available, and [Ollama](https://ollama.com).

```bash
# Models
ollama pull qwen3.5:9b
ollama pull nomic-embed-text

# Backend
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements-dev.txt
echo 'DATABASE_URL=postgresql+psycopg://USER:PASS@localhost:5432/jarvis' > .env
echo 'JARVIS_PASSCODE=choose-a-passcode' >> .env   # see "Access" below
python -m app.models.create_tables   # tables + default user
python -m piper.download_voices --download-dir data/voices \
  en_GB-alan-medium en_US-ryan-medium   # JARVIS / ULTRON voices (~60 MB each)
# Speech-to-text (base.en, ~140 MB) downloads into data/whisper on first use.
# Note: faster-whisper 1.2.1 needs av<18 (pinned to 17.1.0).
python -m scripts.download_wake_word # "Hey Jarvis" wake word models (~4 MB)
python -m app.models.migrate         # new tables/columns, indexes, embeddings
                                     # (re-run after pulling new versions)
python -m pytest                     # optional

# Frontend
cd ../frontend
npm install
```

## Run

```bash
# terminal 1
cd backend && source venv/bin/activate && uvicorn app.main:app --port 8000

# terminal 2
cd frontend && npm run dev
```

Open http://localhost:3000.

**From a phone on the same Wi-Fi:** start the frontend with
`npm run dev -- -H 0.0.0.0` and open `http://<this machine's IP>:3000`
(find the IP with `ipconfig getifaddr en0` on macOS). Only the frontend
is exposed; the backend stays on localhost behind the proxy. Note that
anyone on that network can then chat with Jarvis and read its replies,
and webcam gestures won't work there (browsers only allow the camera on
localhost or HTTPS).

If the backend runs elsewhere, set
`JARVIS_API_URL` (e.g. `JARVIS_API_URL=http://raspberrypi.local:8000 npm run dev`).

Optional backend environment: `LLM_MODEL` (default `qwen3.5:9b`),
`LLM_THINK=true` to enable the model's reasoning mode.

## Using it

- Type in the COMMS panel (or press `/`). Statements like "I'm building
  X" or "I want to finish Y by Friday" are remembered and turned into
  projects/goals in the background; the orb speeds up while Jarvis thinks.
- Jarvis follows the current conversation (its last 6 turns), so
  follow-ups like "and the second one?" work. A conversation ends after
  30 minutes of silence; the panel reloads it on refresh or on another
  device. Older chats still count through long-term memory.
- Tasks and reminders come from chat too: "remind me to call mom at 5",
  "I need to submit the report by Friday", "I called mom". Due
  reminders pop up on the HUD (DONE / +10M / DISMISS) and flare the
  orb; turn on ALERTS for browser notifications while the tab is in the
  background (localhost or HTTPS only). Set `JARVIS_TIMEZONE` (e.g.
  `Asia/Kolkata`) if the backend runs on a machine in another timezone.
- Two modes: **JARVIS** (amber orb, calm) and **ULTRON** (blue neural
  brain, cold and blunt). Same memory and tasks; switch with the mode
  button or `M`. Each device remembers its mode.
- Press **VOICE** (or `V`) to hear replies and reminders, spoken locally
  with Piper: a British voice for JARVIS, a deeper processed one for
  ULTRON. `Esc` stops speaking. Voices are set with `JARVIS_VOICE` /
  `ULTRON_VOICE` (any Piper voice name) and `PIPER_VOICE_DIR`.
- **Talk to it:** hold **TALK** (or hold `Space` when not typing),
  speak, release. Whisper transcribes it locally and sends it. The mic is
  open only while held, and needs localhost or HTTPS (not plain
  `http://<LAN IP>`). `WHISPER_MODEL` picks the model (e.g. `small.en`).
- **It acts, not just talks:** ask it to add, finish, cancel, move or
  delete tasks and reminders ("remind me to call mom at 6", "I sent the
  report"), or to manage projects and goals ("I started a project called
  Portfolio", "put Jarvis on hold", "I'm 60% done with the Pi goal"), and
  it does so with tools before replying; what it did is listed under the
  reply. Deleting asks you to CONFIRM first.
- **Repeating reminders:** "remind me to stretch every day at 4", "take
  out the trash every Monday and Thursday at 8pm", "every weekday at
  9:30". DONE schedules the next one; DISMISS on a plain repeating
  reminder moves it to its next time; "stop repeating …" ends it.
- **Morning briefing and evening review** appear in the HUD (and are
  spoken when VOICE is on) at 08:00 and 21:00: what's overdue, due and
  reminded today, goal deadlines; then what you finished, what's left and
  tomorrow. Set `JARVIS_MORNING_BRIEFING` / `JARVIS_EVENING_REVIEW` to
  another `HH:MM` or `off`. `POST /routines/morning/run` writes one now.
- **Wake word:** turn on **WAKE** (or `W`) and say "Hey Jarvis" (in
  either mode). A chime plays, you speak, and it sends when you pause.
  While on, the mic stays open and the latest 2.5s of audio goes to the
  backend every half second, where openWakeWord's local model scores it;
  nothing is stored. It pauses while recording, thinking or speaking.
  `WAKE_WORD_THRESHOLD` (default `0.5`) trades misses for false wakes.
  The pretrained models are CC BY-NC-SA 4.0 (non-commercial use).
- Drag / scroll to spin and zoom the orb, `G` for webcam hand gestures,
  `R` to reset.
- API docs: http://localhost:8000/docs

**Security:** the API has no authentication. Keep it on localhost (the
default) until auth exists; don't run uvicorn with `--host 0.0.0.0` on a
shared network.

## Access

With `JARVIS_PASSCODE` set in `backend/.env`, the API (everything except
`/` and `/auth`) needs a session: the HUD shows a passcode screen, and a
correct passcode gives that browser a 30-day httpOnly cookie (only its
hash is stored, in `auth_sessions`). **LOCK** signs the browser out. Five
wrong passcodes in five minutes pause logins for the rest of the window.
Scripts and other devices can send `Authorization: Bearer <token>` with
`JARVIS_API_TOKEN` set. Without a passcode the API is open to anyone who
can reach it, and the HUD says so (API OPEN). Over plain HTTP on a LAN
the passcode and cookie travel unencrypted; serve HTTPS and set
`JARVIS_COOKIE_SECURE=1` if that matters.

## Credits

The orb UI is based on [ULTRON Orb UI](https://sagartamang.com/projects/ultron)
by Sagar Tamang, MIT licensed (see `frontend/LICENSE`).
