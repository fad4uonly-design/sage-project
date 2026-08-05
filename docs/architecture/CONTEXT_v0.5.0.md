# SAGE v0.5.0 — Cognitive Context Engine

**Status:** Implemented  
**Builds on:** v0.4.0 Automation  
**Architecture stance:** Core frozen — this milestone adds capability, not redesign

---

## Goal

Give SAGE **persistent awareness** of the user’s world:

- What projects and goals are active  
- What is running / waiting  
- What deserves attention (suggestions only)  
- Continuity across sessions  
- Reflection that turns execution into improvement  

---

## Components

```
Cognitive Context Engine
├── Persistent Context State
├── Project Manager
├── Goal Engine
├── Context Fusion
├── Proactive Suggestions (advisory)
├── Session Continuity
└── Reflection Engine (feedback loop)
```

```
Memory + Knowledge Graph + Projects + Goals
 + Automation + Approvals + Audit
                ↓
        Context Fusion
                ↓
     Orchestrator / Agents
```

---

## 1. Project Manager (`sage.projects`)

First-class projects with:

- objectives, domain, priority, progress, tags  
- links to documents, memories, goals, workflows, decisions, notes, risks, entities  

```bash
sage project list
sage project create --name SAGE --description "Personal AI OS" --activate
```

---

## 2. Goal Engine (`sage.goals`)

Horizons: **long · medium · daily**

- parent/child dependencies  
- success metrics  
- progress + completion  

```bash
sage goal create --title "Build AI Operating System" --horizon long
sage goal create --title "Write context tests" --horizon daily
sage goal complete --id <goal_id>
sage goal list
```

---

## 3. Context Fusion (`CognitiveContextEngine.fuse`)

Produces `UnifiedContext` including:

| Field | Source |
|---|---|
| active_projects | Project Manager |
| goals / open_tasks | Goal Engine |
| priorities | ranked goals |
| recent_memories | Memory System |
| graph_highlights | Knowledge Graph |
| running_workflows | workflow_runs |
| pending_approvals | Approval Engine |
| recent_documents | knowledge_documents |
| long_term_interests | context_state + learning patterns |
| suggestions | proactive_suggestions |
| environment | time/season (local, no telemetry) |
| session | SessionContinuity |

`as_orchestrator_context()` flattens this for the Orchestrator.

---

## 4. Proactive Intelligence

Suggestions are **never auto-executed**.

Examples:

- Stale project not touched in ≥7 days  
- Pending approvals  
- Unfinished workflows  
- Agriculture interest → irrigation/weather briefing hint  
- Daily goals with no progress  

```bash
sage context
sage context --refresh
sage ask "what needs attention?"
```

---

## 5. Session Continuity

On boot (`ContextModule._on_start` → `bootstrap_session`):

- Restore active project pointer  
- Capture unfinished workflows & pending approvals  
- Refresh suggestions  
- Snapshot context (`context_snapshots`)  

Conversation turns store a short `last_conversation_summary` for continuity.

---

## 6. Reflection Engine (`sage.reflection`)

Loop:

```
Execute → Audit → Reflect → Learn → Improve
```

Reviews:

- workflow success/failure rates  
- repeated audit failures  
- skill usage  
- KG density  
- confidence calibration hints  

```bash
sage reflect
```

Scheduled daily at 04:15 UTC when scheduler enabled.

---

## Schema

Migration **v5** (`context_v050`):

- `projects`, `project_links`  
- `context_goals`  
- `context_snapshots`, `context_state`  
- `reflections`  
- `proactive_suggestions`  

---

## Boot order (additive)

```
… → automation → projects → goals → context → reflection → plugins → …
```

---

## Compatibility

- No breaking changes to v0.4 APIs  
- Orchestrator gains optional context fusion  
- Version **0.5.0**

---

## Next

**v0.6.0 — User Experience** (web, desktop, mobile, voice, REST/WS) presenting these capabilities without changing core structure.
