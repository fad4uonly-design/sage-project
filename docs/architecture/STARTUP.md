# SAGE Startup & Shutdown Sequence

## Overview

SAGE boots like an operating system: configuration first, then infrastructure, then intelligence modules, then extensions, then the user-facing surface. Every stage is observable, ordered, and reversible.

```
┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐
│  Config  │──▶│ Logging  │──▶│    DI    │──▶│    DB    │──▶│  Events  │
└──────────┘   └──────────┘   └──────────┘   └──────────┘   └──────────┘
                                                                  │
     ┌────────────────────────────────────────────────────────────┘
     ▼
┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐
│  Memory  │──▶│Knowledge │──▶│  Models  │──▶│Reasoning │──▶│ Learning │
└──────────┘   └──────────┘   └──────────┘   └──────────┘   └──────────┘
                                                                  │
     ┌────────────────────────────────────────────────────────────┘
     ▼
┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐
│Planning  │──▶│  Tools   │──▶│  Agents  │──▶│ Plugins  │──▶│  Files   │
└──────────┘   └──────────┘   └──────────┘   └──────────┘   └──────────┘
                                                                  │
     ┌────────────────────────────────────────────────────────────┘
     ▼
┌──────────────┐   ┌──────────────┐   ┌──────────────┐
│ Conversation │──▶│ Health Check │──▶│ system.ready │
└──────────────┘   └──────────────┘   └──────────────┘
```

---

## Detailed Stages

### Stage 0 — Process entry

- CLI (`sage start`) or library (`SageEngine.create()`)
- Resolve working / data directories
- Load `.env` if present

### Stage 1 — Configuration

1. Load built-in defaults (`sage/config/defaults.yaml`)
2. Merge user YAML (`$SAGE_DATA_DIR/config/sage.yaml` if exists)
3. Apply environment variables (`SAGE_*`)
4. Apply CLI overrides
5. Validate with Pydantic → `Settings` object

**Failure mode:** exit with clear validation errors. No partial boot.

### Stage 2 — Logging

1. Configure `structlog` / stdlib logging from `Settings`
2. Attach console + rotating file handlers under `data/logs/`
3. Bind context: `sage_version`, `env`, `session_id`

### Stage 3 — DI Container

1. Create empty `Container`
2. Register `Settings` as singleton
3. Remaining services register as modules initialize

### Stage 4 — Database

1. Ensure data directories exist
2. Open SQLite connection (`SAGE_DB_PATH`)
3. Run pending migrations
4. Register `Database` in DI

### Stage 5 — Event Bus

1. Construct `EventBus`
2. Register in DI
3. Enable internal audit subscriber (optional, config-gated)

### Stage 6 — Core modules (dependency order)

For each module implementing `SageModule`:

1. `module = ModuleClass(container)`
2. `await module.initialize()` — allocate resources, prepare state
3. Register service façade(s) in DI
4. Subscribe to relevant events
5. Record module as `INITIALIZED`

**Order (Phase 1–3):**

| Order | Module | Depends on |
|------:|---|---|
| 1 | MemorySystem | DB, Events |
| 2 | KnowledgeManager | DB, Events, Files (light) |
| 3 | ModelRouter | Config |
| 4 | ReasoningEngine | Models, Memory |
| 5 | LearningEngine | Memory, Events |
| 6 | PlanningEngine | Memory, Reasoning |
| 7 | ToolManager | Config, Events |
| 8 | AgentRegistry / Orchestrator | Tools, Reasoning, Planning |
| 9 | PluginManager | full container |
| 10 | FileManager | Events, Knowledge |
| 11 | ConversationEngine | Memory, Reasoning, Agents, Models |

Modules not yet implemented register as **Null / Stub** implementations so the graph still boots.

### Stage 7 — Plugins

1. Scan `plugins/` and configured paths
2. Validate manifests
3. Load enabled plugins
4. Call `plugin.on_load(container)`
5. Failures are isolated — one bad plugin does not halt boot (logged + skipped)

### Stage 8 — Background services

1. Start `Scheduler` (consolidation jobs, watchers)
2. Start file watchers if enabled
3. Start API server if enabled (Phase 4)

### Stage 9 — Health & ready

1. Query each module `health()` → aggregate `SystemHealth`
2. If any **critical** module is unhealthy → abort boot
3. Emit `system.ready` event with boot metrics
4. Transition engine state: `STARTING` → `RUNNING`

### Stage 10 — User surface

- CLI interactive loop, or
- API server await, or
- Embedded library returns `SageEngine` handle

---

## Shutdown Sequence

Triggered by: SIGINT/SIGTERM, `sage stop`, or `engine.shutdown()`.

```
RUNNING → STOPPING → STOPPED
```

1. Emit `system.shutting_down`
2. Stop accepting new conversation / API work
3. Drain in-flight agent tasks (with timeout)
4. Stop scheduler and file watchers
5. Unload plugins (reverse order)
6. Call `module.shutdown()` reverse init order
7. Flush memory consolidator if dirty
8. Close database
9. Flush and close logs
10. Emit final process exit

**Timeouts:** each stage has a configurable grace period; force-cancel after grace.

---

## Engine States

```python
class EngineState(str, Enum):
    CREATED = "created"
    STARTING = "starting"
    RUNNING = "running"
    DEGRADED = "degraded"   # running but non-critical module failed
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"
```

---

## Boot metrics (emitted on ready)

- `boot_duration_ms`
- `modules_initialized`
- `modules_failed`
- `plugins_loaded`
- `db_migration_version`

---

## Failure policy

| Component | Critical? | On failure |
|---|---|---|
| Config | Yes | Abort |
| Logging | Yes | Abort (fallback stderr) |
| Database | Yes | Abort |
| Event Bus | Yes | Abort |
| Memory | Yes | Abort |
| Knowledge | No (early) | Degrade + stub |
| Models | No | Fall back to StubAdapter |
| Reasoning | No | Degrade |
| Learning | No | Degrade |
| Planning | No | Degrade |
| Agents | No | Degrade |
| Plugins | No | Skip plugin |
| Files | No | Degrade |
| Conversation | Yes (if CLI/API) | Abort if UI requires it |
