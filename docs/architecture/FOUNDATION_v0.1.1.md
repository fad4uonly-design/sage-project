# SAGE v0.1.1 — Core Foundation Complete

**Status:** Implemented  
**Baseline:** v0.1.0 architecture approved with strategic adjustments

---

## Goal

Finish the operating-system foundation before expanding intelligence (M2).  
Add the missing control-plane services that make every later feature safer and more maintainable.

---

## What was added

### 1. Cognitive Orchestrator (`sage.orchestrator`)

The missing “brain” between Conversation and modules:

```
User → Conversation Engine → Orchestrator
         → Intent Analyzer
         → Execution Plan (pipeline steps)
         → Memory / Knowledge / Reasoning / Planning / Agents / Tools
         → Composed Response
```

- Rule-based intent analysis (model-assist ready later)
- Explicit pipeline steps with per-step timing and errors
- Conversation engine no longer hard-routes domains — it delegates

### 2. Permission Manager (`sage.permissions`)

Capability tokens for plugins/tools/agents:

| Permission | Dangerous? |
|---|---|
| filesystem.read / write | write = yes |
| internet | yes |
| shell | yes |
| database, email, camera, microphone | yes |
| secrets.read / write | yes |
| memory.read / write | no |
| tools.invoke, agents.dispatch | no |

- Dangerous permissions are **never** auto-approved
- `require()` raises `PermissionDenied`
- Plugin loader calls `request()` from manifest permissions

### 3. Secrets Manager (`sage.secrets`)

- Encrypted-at-rest secret store in SQLite
- PBKDF2 + HMAC-SHA256 authenticated encryption (stdlib)
- Master key: `SAGE_MASTER_KEY` env or `$DATA_DIR/config/master.key`
- Seed from settings API keys; rotate / list / delete APIs

### 4. Health Monitor (`sage.monitor`)

- Continuous resource snapshot (RSS, loadavg CPU estimate)
- Module health aggregation
- Persists snapshots to `health_snapshots`
- Scheduler job every 5 minutes
- Engine `health()` prefers monitor probe

### 5. Configuration Manager (`sage.config.manager`)

- Typed `Settings` + runtime overrides + DB profile store
- YAML/JSON export
- Profile load/save (`config_store` table)

### 6. Logging upgrades

- Rotating file handlers: `sage.log`, `sage-debug.log`, `sage-modules.log`
- Dedicated **audit** channel → `sage-audit.log`
- `audit(action, **fields)` helper

### 7. Real Scheduler

- Interval jobs
- Daily jobs (`daily_at="HH:MM"`)
- Weekly jobs (`weekly_on=0-6`)
- Built-in: memory consolidate, monitor snapshot, heartbeat, nightly maintenance

### 8. Enhanced (Cognitive) Memory

Pipeline:

```
Store → fingerprint → duplicate detection → importance scoring
     → term tags → version history → relationship links → events
```

Consolidation adds: merge duplicates, rescore, relate, promote, expire.

### 9. Schema v2

New tables: `secrets`, `permission_grants`, `memory_relations`, `memory_versions`,
`config_store`, `audit_log`, `health_snapshots` + memory `content_hash`/`version` columns.

---

## Boot order (v0.1.1)

```
database → secrets → permissions → config → memory → knowledge → models
→ reasoning → learning → planning → tools → agents → plugins → files
→ orchestrator → monitor → conversation
```

---

## Revised roadmap (approved)

| Version | Focus |
|---|---|
| **0.1.1** | Core foundation complete ← **this release** |
| **0.2.0** | Intelligence layer — knowledge graph, reasoning strategies, learning, retrieval |
| **0.3.0** | Domain intelligence — Agriculture, Finance, Accounting, Business, Programming agents |
| **0.4.0** | Automation — workflows, advanced tools, plugin marketplace hooks |
| **0.5.0** | UX — web dashboard, desktop, REST API, voice |
| **1.0.0** | Production — security hardening, backup/recovery, stable APIs |

---

## Deliberately deferred (not forgotten)

- Full knowledge graph (v0.2)
- Domain agents (v0.3)
- Plugin sandboxing / digital signatures (v0.4+)
- Fernet via `cryptography` package (optional upgrade path for secrets)
- psutil-grade metrics (optional dependency)
