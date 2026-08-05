# SAGE v0.6.0 — User Experience Foundations

**Status:** Implemented  
**Architecture:** Core remains **frozen** (see `ARCHITECTURE_FREEZE_v1.md`)

---

## What this milestone adds

1. **Architecture freeze declaration** (v1 core)  
2. **Knowledge Discovery Engine** (additive capability)  
3. **Versioned REST API** (`/api/v1/*`)  
4. **WebSocket chat** (`/api/v1/ws/chat`)  
5. **Web Dashboard** (single-page client)  
6. **`sage serve`** CLI to boot API + dashboard  

Desktop/mobile/voice remain future clients against the same API.

---

## Knowledge Discovery Engine

Package: `sage.discovery`

Mines:

- Graph hubs & orphans  
- Dominant relation types  
- Agriculture / business hypotheses  
- Memory vs KG gaps  
- Soft contradiction hints  
- Workflow usage gaps  

Outputs **insights only** (optionally mirrored as context suggestions).  
Never mutates the graph or runs workflows autonomously.

```bash
sage discover
```

---

## API (v1)

Base: `/api/v1`

| Method | Path | Purpose |
|---|---|---|
| GET | `/status` | Version, state, modules |
| GET | `/health` | Module health detail |
| POST | `/ask` | One-shot conversation |
| GET | `/context` | Fused cognitive context |
| GET/POST | `/projects`, `/goals` | Project & goal CRUD |
| GET/POST | `/memory` | Recall / store |
| GET | `/knowledge/stats`, `/knowledge/search` | Graph |
| GET/POST | `/workflows`, `/workflows/run` | Workflow engine |
| GET/POST | `/automations` | Automation manager |
| GET | `/audit` | Execution audit |
| GET/POST | `/approvals/*` | Approval engine |
| POST | `/discovery/run` | Knowledge discovery |
| POST | `/reflect` | Reflection engine |
| GET | `/agents`, `/skills`, `/tools` | Catalogs |
| WS | `/ws/chat` | Streaming multi-turn chat |

Dashboard static UI: `/` and `/static/*`

### Run

```bash
sage serve --host 0.0.0.0 --port 8742
# open http://localhost:8742/
```

Or enable in config:

```yaml
api:
  enabled: true
  host: 0.0.0.0
  port: 8742
```

---

## Web Dashboard views

- Overview (health, modules)  
- Chat (WebSocket)  
- Context & suggestions  
- Projects & goals  
- Workflows  
- Automation  
- Knowledge graph  
- Audit  
- Discovery  
- Approvals  

---

## Compatibility

- Frozen core untouched in public contracts  
- API is **additive**  
- Version **0.6.0**  
- Schema migration **v6** (discovery_insights)

---

## Toward v1.0

Use this API as the stability surface. Production checklist remains:

- backup/restore, security audits, performance, full docs, stress tests  

Future clients (desktop, mobile, voice) should consume `/api/v1` only.
