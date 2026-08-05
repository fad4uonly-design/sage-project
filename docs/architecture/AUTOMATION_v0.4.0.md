# SAGE v0.4.0 — Automation

**Status:** Implemented  
**Builds on:** v0.3.2 Skill Library

---

## Goal

Enable SAGE to **safely execute complete, explainable, multi-step tasks** across domains using:

1. Workflow Engine  
2. Tool Framework  
3. Approval Engine  
4. Execution Audit  
5. Automation Manager  
6. Plugin Runtime extensions (agents / skills / tools / workflows)

---

## Architecture

```
User / Scheduler / Event
         ↓
 Automation Manager
         ↓
 Workflow Engine ──► Skills ──► Agents
         │              ↓
         │            Tools
         │              ↓
         ├──── Approval Engine
         └──── Execution Audit
```

### Boot order (new modules)

```
… → decision → audit → approval → tools → skills → workflow
  → capabilities → agents → automation → plugins → …
```

---

## 1. Workflow Engine (`sage.workflow`)

Stateful process manager.

| Feature | Support |
|---|---|
| Sequential steps | ✅ `next` |
| Parallel branches | ✅ `StepType.PARALLEL` |
| Conditionals | ✅ `StepType.CONDITION` + `when` / `if_true` / `if_false` |
| Loops | ✅ `StepType.LOOP` over context list |
| Retries | ✅ `retry.max_attempts` / `delay_seconds` |
| Timeouts | ✅ per-tool via Tool Framework |
| Checkpoints / resume | ✅ `checkpoint` + `resume(run_id)` |
| Approval gates | ✅ `StepType.APPROVAL` / tool checks |
| Rollback | Partial — failed runs preserve history; compensating steps via `on_error` |

### Step types

`skill` · `tool` · `agent` · `decision` · `condition` · `parallel` · `loop` · `approval` · `set` · `memory` · `notify`

### Built-in workflows

- `business_expansion_report` — SWOT → Finance agent → Risk → Decision → Exec summary → Memory  
- `morning_farm_briefing` — Weather tool → Crop skill → Agriculture agent → Summary  
- `document_ingest_chain` — Outline skill → Memory (event-driven)

### CLI

```bash
sage run-workflow business_expansion_report --task "Expand into city markets"
```

---

## 2. Tool Framework (`sage.tools`)

Standardized tools with:

- category  
- parameters schema + required validation  
- permissions  
- approval integration  
- timeout  
- audit logging  

### Built-in tools

| Category | Tools |
|---|---|
| utility | echo, current_time, calculator |
| files | read_file, write_file, list_dir |
| weather | weather (offline stub) |
| database | sqlite_query (SELECT only) |
| spreadsheet | csv_summary |
| document | markdown_outline, json_load |

Network/shell tools remain gated by config + approval (not registered by default).

---

## 3. Approval Engine (`sage.approval`)

Levels:

| Level | Behavior |
|---|---|
| `automatic` | Run without prompt |
| `ask_once` | Prompt once per session/principal |
| `always_ask` | Prompt every time |
| `deny` | Block |

```bash
sage approve <request_id>
sage approve <request_id> --deny
```

Defaults: calculator/echo/time automatic; write/delete/shell sensitive.

Tests use `auto_approve_in_test=True` for non-interactive CI.

---

## 4. Execution Audit (`sage.audit`)

Every significant action can record:

- kind (workflow / skill / tool / agent / automation / system)  
- workflow run id, skill id, tool name, agent id  
- status, summary, reasoning, confidence  
- duration, approvals, detail JSON  

```bash
sage audit --limit 20
sage audit --kind workflow
```

Also mirrored to structured `sage-audit.log` via `logging.audit`.

---

## 5. Automation Manager (`sage.automation`)

Triggers:

- **interval** — scheduler dispatch  
- **cron-like** — daily_at + weekday  
- **event** — e.g. `knowledge.document.ingested`  
- **manual** — CLI / API  

```bash
sage automations
sage automations --enable morning_farm_briefing
sage automations --run morning_farm_briefing
```

Built-in jobs (mostly opt-in via `--enable`):

- `morning_farm_briefing`  
- `sunday_financial_summary`  
- `on_document_ingested` (enabled by default)

---

## 6. Plugin Runtime

Manifest now declares optional extension points:

```yaml
agents: []
skills: []
tools: []
workflows: []
```

Plugins still register concrete objects in `on_load(container)` against:

- `AgentOrchestrator` / custom registration  
- `SkillLibrary.register`  
- `ToolManager.register`  
- `WorkflowEngine.register`

---

## Workflow Marketplace (foundation)

Higher-level automations are **workflow definitions** composed of existing skills, agents, and tools.  
Install path today: drop definition via `WorkflowEngine.register` or ship inside a plugin.  
Future marketplace can distribute YAML/JSON definitions without core changes.

---

## Schema

Migration **v4** (`automation_v040`):

- `workflow_definitions`, `workflow_runs`, `workflow_step_runs`  
- `approval_policies`, `approval_requests`  
- `execution_audit`  
- `automation_jobs`  

---

## Compatibility

- All v0.3.x APIs preserved  
- New modules are additive  
- Version **0.4.0**

---

## Beyond v0.4.0

1. **Context Engine** — persistent situational state across sessions  
2. **UX** — web / desktop / mobile / voice  
3. Richer tools (email, calendar, real weather APIs) behind approval  
4. Workflow marketplace packaging format  

---

## Tests

See `tests/unit/test_automation.py`.
