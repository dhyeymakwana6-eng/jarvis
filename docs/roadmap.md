# Project D.0 Roadmap

## Phase 1 — Environment Setup

Status: Complete

## Phase 2 — Architecture

Status: Complete

## Phase 3 — PostgreSQL Connection

Status: Complete

## Phase 4 — Core Database Models

Status: Complete

## Phase 5 — Memory CRUD

Status: Complete

## Phase 6 — Memory Search

Status: Complete

## Phase 7 — Memory Service Layer

Status: Complete

### Task 1 — Service Structure

Status: Complete

### Task 2 — Memory Retriever

Status: Complete

### Task 3 — Memory Ranker

Status: Complete

### Task 4 — Context Builder

Status: Complete

### Task 5 — Memory Service

Status: Complete

### Task 6 — API Integration

Status: Complete

---

## Phase 8 — Local LLM Integration (Ollama)

Status: Complete

### Task 1 — Install Ollama

Status: Complete

### Task 2 — Download Local Model

Status: Complete

### Task 3 — Verify Local Model

Status: Complete

### Task 4 — Create LLM Service

Status: Complete

### Task 5 — End-to-End Chat Validation

Status: Complete

---

## Phase 9 — Automatic Memory Extraction

Status: Complete

## Phase 10 — Memory Management

Status: Complete

### Task 1 — Update Endpoint

Status: Complete

### Task 2 — Filtering and Pagination

Status: Complete

### Task 3 — Soft Delete and Restore

Status: Complete

### Task 4 — Similarity Deduplication (pg_trgm)

Status: Complete

### Task 5 — Access Tracking and Importance Decay

Status: Complete

## Phase 11 — Semantic Search

Status: Complete

### Task 1 — Embeddings on Memory (pgvector + nomic-embed-text)

Status: Complete

### Task 2 — Semantic Search Endpoint

Status: Complete

### Task 3 — Hybrid Retrieval in Chat (semantic + keyword + importance)

Status: Complete

### Task 4 — Embedding-Based Deduplication

Status: Complete

### Task 5 — HNSW Vector Index and Re-embedding Migration

Status: Complete

## Phase 12 — User Profile Engine

Status: Complete

### Task 1 — Structured Profile Model (User.profile JSONB)

Status: Complete

### Task 2 — LLM Profile Builder and /profile Endpoints

Status: Complete

### Task 3 — Profile Injected into Chat Prompt

Status: Complete

### Task 4 — Background Extraction and Profile Refresh

Status: Complete

### Task 5 — Contradiction Detection (CONFLICT supersedes old memory)

Status: Complete

### Task 6 — Durable Extraction via Conversation Log

Status: Complete

### Task 7 — Unit Test Suite (pytest)

Status: Complete

## Phase 13 — Goal & Project Tracking

Status: Complete

### Task 1 — Project and Goal Models (status, deadlines, progress, soft delete)

Status: Complete

### Task 2 — /projects and /goals API

Status: Complete

### Task 3 — Projects and Goals in Chat Context (deadlines, overdue)

Status: Complete

### Task 4 — Automatic Tracking from Chat (LLM, validated)

Status: Complete

## Phase 14 — Task & Reminder System

Status: Complete

### Task 1 — Task Model and /tasks API (due/remind times, priority, soft delete)

Status: Complete

### Task 2 — Tasks in Chat Context (due today, overdue)

Status: Complete

### Task 3 — Tasks and Reminders from Chat (LLM, validated)

Status: Complete

### Task 4 — Reminder Delivery (orb HUD + browser notification)

Status: Complete

## Phase 15 — Decision Engine

Status: Deferred (low value for now; the decisions table stays for later)

## JARVIS / ULTRON Modes

Status: Complete

Two personas over the same memory, profile, goals and tasks: JARVIS
(amber orb, calm) and ULTRON (blue neural brain, cold and blunt). Switch
with the MODE button or M; each device remembers its mode. Phase 16
gives each mode its own voice.

## Phase 16 — Voice System

Status: Complete (fully local)

### Task 1 — Spoken Replies (Piper TTS, a voice per mode)

Status: Complete

### Task 2 — Push-to-Talk Speech Input (local Whisper)

Status: Complete

### Task 3 — Wake Word (optional)

Status: Complete

"Hey Jarvis" with openWakeWord's pretrained ONNX models, run directly with
onnxruntime (no new dependencies). The browser streams 16 kHz audio windows
to `POST /voice/wake`; a detection chimes and starts a hands-free recording
that ends on a pause. Off by default (WAKE / `W`), paused while recording,
waiting for a reply or speaking.

## Phase 17 — Agent Framework

Status: In Progress

### Task 1 — Task Tools in Chat

Status: Complete

The chat model calls tools (Ollama tool calling, same local model) to
create, complete/cancel, reschedule, list and delete tasks before it
replies, so the reply reflects what actually happened. Each action shows
under the reply and is logged on the turn (`conversations.actions`);
deleting waits for CONFIRM. The prompt always carries today's and
tomorrow's date. The background tracker stays as a safety net: when the
agent acted on tasks it skips new tasks (no duplicates) and the tasks the
agent touched, and still applies changes the agent missed.
`JARVIS_LIVE_LLM=1 pytest tests/test_agent_live.py` checks the real model.

### Task 2 — Project and Goal Tools

Status: Complete

Tools to start, finish, pause, drop, resume and rename projects (and set
their next step), and to add goals and update their progress, deadline
and status; deleting either waits for CONFIRM. The chat context labels
ids by type (`[task 7]`, `[project 3]`, `[goal 5]`). The tracker safety
net works per kind: for each kind the agent acted on, it skips new items
and the items the agent touched.

## Phase 18 — Automation Engine

Status: Complete

### Task 1 — Repeating Tasks

Status: Complete

Tasks can repeat (`tasks.recurrence`: daily, weekdays, weekly:mon,thu,
days:N, monthly/monthly:D; app/core/recurrence.py). Completing one marks
it done and creates the next occurrence; dismissing a repeating reminder
without a deadline moves it to its next time; cancelling stops it. Missed
occurrences are skipped, times keep their local wall-clock time across
DST, and weekly/monthly rules are pinned to their day. The chat agent
sets and stops repeats (`repeat` on create_task/update_task); weekday
rules start on the first allowed day regardless of the date the model
picks. Needs `python -m app.models.migrate`.

### Task 2 — Routines (morning briefing, evening review)

Status: Complete

A scheduler thread (started with the app) writes the morning briefing
(overdue, today's tasks and reminders, goal deadlines) and evening review
(done today, still open, tomorrow) at `JARVIS_MORNING_BRIEFING` /
`JARVIS_EVENING_REVIEW` (default 08:00 / 21:00, `off` to disable). Facts
come from the database; the local LLM words them in the persona last
chatted with, falling back to the plain facts if Ollama is down. One run
per routine per day (`routine_runs`), delivered up to 4 hours late if the
backend was down. The HUD polls `/routines/due`, shows a card and speaks
it when VOICE is on; `POST /routines/{morning|evening}/run` writes one on
demand.

## Phase 19 — Raspberry Pi Deployment

Status: Not Started

## Phase 20 — Multi-Device Ecosystem

Status: In Progress

### Task 1 — Local HTTPS and Installable App

Status: Complete

`npm run dev:lan` serves the frontend over HTTPS on the LAN with a
certificate from a private local CA (`frontend/scripts/lan-https.sh`,
system openssl only; the certificate is reissued each run for localhost,
the Mac's .local name and its LAN IPs). Phones that trust the CA get the
mic (TALK, wake word) and notifications. A web app manifest and icons make
it installable on the home screen (standalone, no offline cache).

### Task 2 — Live Sync, One Speaker

Status: Not Started

### Task 3 — Devices Panel

Status: Not Started

### Task 4 — Synced Settings

Status: Not Started

