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

* User
* Memory (with pgvector embedding)
* Project
* Goal
* Conversation
* Decision

### API Layer

* Memory API

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
ContextBuilder (top 10)
↓
LLMService
↓
Response
↓
MemoryPipeline stores new memories from the query

If Ollama embeddings are unavailable, retrieval falls back to
keyword-only ranking.

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
* UserProfileManager (Future)

### Productivity Services

* GoalManager
* ProjectManager
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

⏳ Local LLM Integration (Ollama)

⏳ Automatic Memory Extraction

⏳ User Profile Engine

⏳ Goal & Project Tracking

⏳ Task Management

⏳ Voice System

⏳ Agent Framework

⏳ Automation Engine

⏳ Raspberry Pi Deployment

⏳ Multi-Device Ecosystem
