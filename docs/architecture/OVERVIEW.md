# SAGE Architecture Overview

**Version:** 0.1.0 (Milestone 0 — Architecture & Interfaces)  
**Status:** Foundation design — approved structure, interfaces defined, startup sequence implemented

---

## 1. Design Goals

SAGE is a **personal AI operating system**. It is not a single LLM wrapper or chatbot session. It is a long-running, modular platform that:

1. Boots like a system (config → services → health → ready)
2. Persists memory and knowledge across sessions
3. Reasons and plans with explainable steps
4. Learns continuously from interaction and outcomes
5. Delegates work to specialized agents and tools
6. Extends via plugins without core modifications
7. Keeps all user data local and user-owned

### Non-goals (for early phases)

- Replacing general-purpose cloud assistants feature-for-feature
- Training foundation models from scratch
- Multi-tenant SaaS hosting (SAGE is single-user / personal first)

---

## 2. Architectural Style

| Choice | Rationale |
|---|---|
| **Modular monolith** (initial) | Simple deploy, clear module boundaries, easy local run |
| **Event-driven communication** | Loose coupling; modules react without hard dependencies |
| **Dependency injection** | Testability, swappable implementations |
| **Ports & adapters (hexagonal)** | AI models, storage, UI are replaceable |
| **Interface-first** | Every module has a Protocol/ABC; implementations are injectable |
| **Async-capable core** | Long-running jobs, I/O, and multi-agent work |

We start as a well-factored modular monolith. Individual services can be extracted later if needed without rewriting domain logic.

---

## 3. Layered View

```
┌─────────────────────────────────────────────────────────────┐
│                     User Interfaces                          │
│              CLI · Web · Desktop · Voice · API               │
├─────────────────────────────────────────────────────────────┤
│                   Conversation Engine                        │
├─────────────────────────────────────────────────────────────┤
│  Agents  │  Planning  │  Reasoning  │  Learning  │  Tools   │
├─────────────────────────────────────────────────────────────┤
│           Memory System     │     Knowledge Manager          │
├─────────────────────────────────────────────────────────────┤
│  Model Adapters  │  Plugin System  │  File Manager           │
├─────────────────────────────────────────────────────────────┤
│              Core Engine · Event Bus · Config · DI           │
├─────────────────────────────────────────────────────────────┤
│           Database (SQLite → optional larger stores)         │
└─────────────────────────────────────────────────────────────┘
```

**Dependency rule:** outer layers depend inward on interfaces. Core never depends on UI or specific LLM vendors.

---

## 4. Module Catalog

| Module | Package | Responsibility |
|---|---|---|
| **Core Engine** | `sage.core` | Lifecycle, DI container, module registry, health, job scheduling |
| **Bootstrap** | `sage.core.bootstrap` | Ordered startup / shutdown sequence |
| **Config** | `sage.config` | Typed settings from env, YAML, defaults |
| **Event Bus** | `sage.events` | Pub/sub event distribution |
| **Memory** | `sage.memory` | Store/retrieve/consolidate personal & episodic memory |
| **Knowledge** | `sage.knowledge` | Document ingest, categorize, search, relationships |
| **Reasoning** | `sage.reasoning` | Multi-step logic, decisions, explanations |
| **Learning** | `sage.learning` | Patterns, preferences, confidence, consolidation |
| **Planning** | `sage.planning` | Goals, plans, schedules, prioritization |
| **Agents** | `sage.agents` | Specialized agent base + registry + orchestration |
| **Plugins** | `sage.plugins` | Discover, load, lifecycle of plugins |
| **Tools** | `sage.tools` | Register and invoke external tools |
| **Conversation** | `sage.conversation` | Dialogue state, context, personality |
| **Files** | `sage.files` | Index, watch, metadata, categorization |
| **DB** | `sage.db` | Persistence abstraction (SQLite first) |
| **Models** | `sage.models` | LLM / embedding provider adapters |
| **Logging** | `sage.logging` | Structured logs, audit trail hooks |
| **API** | `sage.api` | HTTP/WS surface (Phase 4) |
| **UI** | `sage.ui` | CLI now; desktop/web later |

---

## 5. Communication Patterns

### 5.1 Synchronous (direct DI calls)

Used for request/response paths where the caller needs an immediate result:

```
ConversationEngine → ReasoningEngine.reason(query, context)
ConversationEngine → MemorySystem.recall(query)
```

### 5.2 Asynchronous (Event Bus)

Used for side effects and cross-module reactions:

```
FileUploaded
  → KnowledgeManager.ingest
  → MemorySystem.store_episode
  → LearningEngine.observe
  → Notification (UI)
```

### 5.3 Event naming convention

```
{domain}.{entity}.{action}
```

Examples:

- `memory.item.created`
- `knowledge.document.ingested`
- `agent.task.completed`
- `system.health.degraded`
- `conversation.turn.completed`

---

## 6. Startup Sequence

```
1. Parse CLI / env
2. Load configuration (defaults → YAML → env → CLI overrides)
3. Initialize logging
4. Create DI container
5. Open database / run migrations
6. Create Event Bus
7. Register core services in DI
8. Initialize modules in dependency order:
      Config → DB → Events → Memory → Knowledge → Models
      → Reasoning → Learning → Planning → Tools → Agents
      → Plugins → Files → Conversation
9. Load enabled plugins
10. Start background schedulers / watchers
11. Health check all modules
12. Emit system.ready
13. Hand control to UI / API
```

Shutdown reverses the order: stop accepting work → drain jobs → stop plugins → close DB → flush logs.

---

## 7. Data Ownership

| Data | Default store | Notes |
|---|---|---|
| Memories | SQLite `memories` | Importance-ranked, typed |
| Knowledge docs | SQLite + files on disk | Originals in `data/knowledge/` |
| Relationships | SQLite / graph tables | Built by Knowledge + Learning |
| Preferences | SQLite `preferences` | Learned + explicit |
| Tasks / plans | SQLite | Planning engine |
| Plugin settings | SQLite / YAML | Per-plugin |
| Logs | Files under `data/logs/` | Rotated |
| Config | YAML + `.env` | User-editable |

All paths are under a configurable `SAGE_DATA_DIR` (default `./data`).

---

## 8. Model Agnosticism

```
                    ┌──────────────────┐
                    │  ModelRouter     │
                    └────────┬─────────┘
           ┌─────────────────┼─────────────────┐
           ▼                 ▼                 ▼
     StubAdapter       OpenAIAdapter     LocalLLMAdapter
     (offline)         AnthropicAdapter  (llama.cpp, Ollama…)
```

- Interfaces: `LanguageModel`, `EmbeddingModel`
- `ModelRouter` selects provider by config / capability / cost
- Early phases default to **StubAdapter** so the system runs fully offline

---

## 9. Security & Privacy Principles

1. No telemetry without explicit opt-in  
2. API keys only via env / local secret store — never in DB dumps by default  
3. Plugins run with declared permissions (future capability tokens)  
4. Tool execution is gated (allow-list / confirmation policies)  
5. User can export and delete all personal data  

---

## 10. Versioning & Milestones

Semantic versioning (`MAJOR.MINOR.PATCH`).

| Milestone | Version target | Deliverable |
|---|---|---|
| M0 Architecture | 0.1.0 | Structure, interfaces, bootstrap, CLI skeleton |
| M1 Foundation | 0.2.0 | Working Memory + DB + Config + Events |
| M2 Intelligence | 0.3.0 | Knowledge + Reasoning + Learning + Planning stubs→real |
| M3 Automation | 0.4.0 | Agents + Plugins + Tools |
| M4 UX | 0.5.0 | Web/API + richer CLI |
| M5 Advanced | 1.0.0 | Multi-agent autonomy, predictive assistance |

**Rule:** never break existing functionality without an explicit migration path.

---

## 11. Testing Strategy

- **Unit tests** per module against interfaces (fakes/mocks via DI)
- **Integration tests** for startup, event flows, DB
- **Contract tests** for model adapters
- Target: critical paths covered before each milestone merge

---

## 12. Related Documents

- [INTERFACES.md](./INTERFACES.md) — Protocol definitions summary  
- [STARTUP.md](./STARTUP.md) — Detailed boot sequence  
- [FOLDER_STRUCTURE.md](./FOLDER_STRUCTURE.md) — Package map  
- [DATA_MODEL.md](./DATA_MODEL.md) — Persistence schema (M1)  
