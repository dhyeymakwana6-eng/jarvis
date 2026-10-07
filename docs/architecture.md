# Project D.0 Architecture

## Core Architecture

User
↓
API Layer
↓
Service Layer
↓
Memory Layer
↓
Database

---

## Technology Stack

### Frontend

* Next.js + Three.js UI (frontend/)
* Two modes: JARVIS (amber orb, lib/orbScene.ts) and ULTRON (blue
  neural brain, lib/brainScene.ts), both implementing OrbSceneApi
* Chat panel calling /memory/chat through a Next.js proxy, sending the
  mode; the backend picks the persona prompt (LLMService.PERSONAS) and
  stores the mode on each conversation

### Backend

* FastAPI
* Python

### Database

* PostgreSQL

### ORM

* SQLAlchemy

### LLM Layer

* Ollama (Primary)
* OpenAI (Optional Future)
* Other Providers (Future)

---

## Current Components

### Database

* PostgreSQL Connection
* Database Session Management

### Models

* User (with LLM-built JSONB profile)
* Memory (with pgvector embedding, superseded_by link)
* Project (status, next action, soft delete)
* Goal (status, target date, progress, soft delete)
* Conversation
* Decision

### API Layer

* Memory API
* Profile API
* Projects API
* Goals API
* Tasks API
* Reminders API (due / dismiss / snooze; clients poll every 30s)

### Memory Layer

* Memory CRUD (soft delete, restore)
* Keyword Search
* Semantic Search (pgvector, cosine distance, HNSW index)

### Service Layer

* MemoryRetriever
* MemoryRanker
* ContextBuilder
* MemoryService
* EmbeddingService
* LLMService
* MemoryPipeline (extract → classify → score → deduplicate → store)
* ConflictChecker (LLM: same / contradicts / compatible)
* ProfileService
* TrackingService (projects/goals/tasks from chat; chat context)
* TaskService (task chat context; validated task changes from chat)
* ConversationHistory (current session's turns from the conversations log)

---

## Current Response Flow

User Query
↓
EmbeddingService (search_query embedding)
↓
MemoryRetriever (semantic + keyword candidates)
↓
MemoryRanker (hybrid: 0.6 semantic, 0.25 keyword, 0.15 decayed importance)
↓
ContextBuilder (top 10) + ProfileService (cached profile)
  + TrackingService (open projects/goals, deadlines)
  + TaskService (open tasks: overdue / today / upcoming / undated,
    done today; local time, JARVIS_TIMEZONE overrides)
  + ConversationHistory (last 6 turns of the current session;
    a session ends after 30 min idle; capped at ~6k chars)
↓
LLMService
↓
Response
↓
Conversation logged (conversations table)
↓
Background task:
  MemoryPipeline stores new memories from the query
  (a contradicting memory supersedes the old one)
  TrackingService creates/updates projects, goals and tasks the message
  states (task times come back as local "YYYY-MM-DD HH:MM" and are
  validated: past reminders roll to tomorrow or are dropped)
  ↓
  ProfileService rebuilds the profile if memories changed
  Conversation marked memories_processed

On startup, conversations not yet processed (e.g. after a crash)
are processed in a background thread.

## Testing

Tests, from backend/ (database tests run in a rolled-back
transaction and skip if Postgres is down; none need Ollama):

    pip install -r requirements-dev.txt
    python -m pytest

## Schema Changes

From backend/: `python -m app.models.migrate` (idempotent).
Add `--reembed` after changing the embedding model or prefixes.

The default user (DEFAULT_USER_ID) is created on startup and by
create_tables / migrate if missing.

If Ollama embeddings are unavailable, retrieval falls back to
keyword-only ranking. If the chat LLM is unreachable, /memory/chat
returns 503, and background extraction leaves the conversation
unprocessed so it is retried at the next startup.

---

## Service Layer Architecture

### Memory Services

* MemoryRetriever
* MemoryRanker
* ContextBuilder
* MemoryService
* MemoryExtractor

### AI Services

* LLMService
* ProfileService

### Productivity Services

* TrackingService (goals and projects)
* TaskManager
* ReminderManager

### Agent Services

* AgentManager
* ToolManager

### Voice Services

* SpeechToTextManager
* TextToSpeechManager
* WakeWordManager

### Automation Services

* AutomationManager
* WorkflowManager

### Synchronization Services

* SyncManager

---

## Future System Architecture

User
↓
API Layer
↓
Service Layer
├── Memory Services
├── AI Services
├── Productivity Services
├── Agent Services
├── Voice Services
├── Automation Services
└── Synchronization Services
↓
Memory Layer
↓
Database

---

## Design Principles

### Provider Independence

Jarvis must not depend on a single AI provider.

Supported providers may include:

* Ollama
* OpenAI
* Gemini
* Anthropic
* Future LLM Providers

Changing providers must not require architectural changes.

### Local-First Design

Jarvis should function locally whenever possible.

Primary execution target:

* Lenovo LOQ Laptop

Secondary execution target:

* Raspberry Pi

### Long-Term Memory

Jarvis should maintain persistent memory across:

* Conversations
* Projects
* Goals
* Tasks
* User Preferences

### Modularity

Each major capability should exist as an independent service that can be upgraded without affecting the rest of the system.

### Scalability

The architecture should support future additions including:

* Voice Interaction
* Agents
* Automation
* Multi-Device Synchronization
* Personalization
* Learning Systems
* Physical Device Integration

---

## Current Project Status

✅ PostgreSQL Connected

✅ Memory Model Implemented

✅ Memory CRUD Implemented

✅ Memory Search Implemented

✅ Memory Retrieval Implemented

✅ Memory Ranking Implemented

✅ Context Building Implemented

✅ Memory Service Implemented

✅ Local LLM Integration (Ollama)

✅ Automatic Memory Extraction

✅ Semantic Search (pgvector)

✅ User Profile Engine

✅ Goal & Project Tracking

✅ Task Management & Reminders

⏳ Voice System

⏳ Agent Framework

⏳ Automation Engine

⏳ Raspberry Pi Deployment

⏳ Multi-Device Ecosystem
