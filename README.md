# SAGE — Smart Autonomous General Engine

**Tagline:** Learn Better. Think Better. Live Better.

SAGE is a **personal AI operating system** — not a chatbot. It is designed to continuously learn, remember, reason, plan, and assist through a modular, privacy-first architecture that runs locally under the user's full control.

---

## Vision

| Capability | Description |
|---|---|
| **Remember** | Long-term personal, episodic, and semantic memory |
| **Learn** | Continuous improvement from conversations, documents, and outcomes |
| **Understand** | Document ingestion, knowledge graphs, categorization |
| **Think** | Explainable multi-step reasoning and decision making |
| **Plan** | Goals, schedules, workflows, and task prioritization |
| **Act** | Specialized agents and tools that execute real work |
| **Own** | Offline-first, user-controlled data, model-agnostic |

---

## Architecture at a Glance

```
SAGE
├── Core Engine          # Boot, DI, lifecycle, scheduler, coordination
├── Orchestrator         # Intent → plan → module pipeline (cognitive brain)
├── Event Bus            # Loose coupling between modules
├── Permissions          # Capability grants (plugins/tools never unrestricted)
├── Secrets              # Encrypted local credential store
├── Health Monitor       # Continuous resource + module probes
├── Memory System        # Cognitive memory (score, relate, version, consolidate)
├── Knowledge Manager    # Document ingestion & knowledge graph
├── Reasoning Engine     # Deduction, induction, multi-step logic
├── Learning Engine      # Pattern recognition, preference learning
├── Planning Engine      # Goals, schedules, workflows
├── Agent Framework      # Specialized collaborative agents
├── Plugin System        # Extensibility with permission requests
├── Tool Manager         # Gated tool invocation
├── Conversation Engine  # Sessions → Orchestrator → response
├── File Manager         # Indexing, watching, categorization
├── API Layer            # Programmatic access
└── User Interface       # CLI → Desktop → Web → Voice → Mobile
```

Modules communicate through the **Event Bus**, are gated by **Permissions**, and are driven by the **Orchestrator**. Each module is independently testable and follows clean architecture / SOLID principles.

---

## Quick Start

### Requirements

- Python **3.13+**
- pip / venv

### Install

```bash
cd sage
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
```

### Run

```bash
# Boot SAGE and open the interactive CLI
sage start

# Show system status
sage status

# Run a one-shot prompt
sage ask "What do you remember about me?"

# Automation (v0.4.0)
sage run-workflow business_expansion_report --task "Expand greenhouse sales"
sage automations
sage automations --enable morning_farm_briefing
sage automations --run morning_farm_briefing
sage audit --limit 20

# Cognitive context (v0.5.0)
sage project create --name SAGE --description "Personal AI OS" --activate
sage goal create --title "Build AI Operating System" --horizon long
sage context --refresh
sage ask "what needs attention?"
sage reflect

# Run tests
pytest
```

---

## Development Roadmap

| Version | Focus | Status |
|---|---|---|
| **0.1.0** | Architecture, interfaces, modular boot | ✅ |
| **0.1.1** | Core foundation complete — Orchestrator, Permissions, Secrets, Monitor, cognitive Memory | ✅ |
| **0.2.0** | Intelligence layer — Knowledge Graph, strategies, retrieval, learning, explainability, capabilities | ✅ |
| **0.3.0** | Domain intelligence — Agriculture, Finance, Business, Programming + Decision Engine + workflows | ✅ |
| **0.3.1** | Business Intelligence Suite — 12 advisors, BI KG, 40+ workflows | ✅ |
| **0.3.2** | Shared Skill Library — cross-domain reusable skills for automation | ✅ |
| **0.4.0** | Automation — Workflow Engine, Tools, Approval, Audit, Automation Manager | ✅ |
| **0.5.0** | Cognitive Context Engine — projects, goals, fusion, suggestions, reflection | ✅ Current |
| **0.6.0** | User Experience — web, desktop, mobile, voice, REST/WS | Planned |
| **1.0.0** | Production — hardening, backup/recovery, stable APIs | Planned |

See [docs/architecture/](docs/architecture/) — especially [CONTEXT_v0.5.0.md](docs/architecture/CONTEXT_v0.5.0.md) and [AUTOMATION_v0.4.0.md](docs/architecture/AUTOMATION_v0.4.0.md).

---

## Core Principles

1. **Modular** — loose coupling, clear interfaces  
2. **Offline-first** — works without the cloud whenever possible  
3. **Explainable** — transparent reasoning and decisions  
4. **Continuous learning** — improves from use  
5. **Long-term memory** — remembers what matters  
6. **Extensible** — plugins and tools without core changes  
7. **User-owned** — data and intelligence stay local  
8. **Model-agnostic** — adapters for OpenAI, Anthropic, local LLMs, stubs  
9. **Maintainable** — SOLID, DI, tests, semantic versioning  

---

## Project Layout

```
sage/
├── sage/                 # Main package
│   ├── core/             # Core Engine, bootstrap, DI, scheduler
│   ├── config/           # Configuration manager (YAML/JSON/env/runtime)
│   ├── events/           # Event bus
│   ├── orchestrator/     # Cognitive orchestrator
│   ├── permissions/      # Capability grants
│   ├── secrets/          # Encrypted secrets
│   ├── monitor/          # Health monitor
│   ├── memory/           # Cognitive memory
│   ├── knowledge/        # Knowledge manager
│   ├── reasoning/        # Reasoning engine
│   ├── learning/         # Learning engine
│   ├── planning/         # Planning engine
│   ├── agents/           # Agent framework
│   ├── skills/           # Shared Skill Library
│   ├── workflow/         # Workflow Engine
│   ├── approval/         # Approval Engine
│   ├── audit/            # Execution Audit
│   ├── automation/       # Automation Manager
│   ├── projects/         # Project Manager
│   ├── goals/            # Goal Engine
│   ├── context/          # Cognitive Context Engine
│   ├── reflection/       # Reflection Engine
│   ├── plugins/          # Plugin manager
│   ├── tools/            # Tool Framework
│   ├── conversation/     # Conversation engine
│   ├── files/            # File manager
│   ├── db/               # Database layer
│   ├── models/           # AI model adapters
│   ├── api/              # API layer
│   ├── ui/               # User interfaces
│   ├── logging/          # Structured + audit logging
│   ├── utils/            # Shared utilities
│   └── cli.py            # CLI entry point
├── tests/                # Unit & integration tests
├── docs/                 # Architecture & guides
├── data/                 # Runtime data (gitignored contents)
├── plugins/              # External / user plugins
├── scripts/              # Dev & ops scripts
└── examples/             # Usage examples
```

---

## License

MIT — see [LICENSE](LICENSE).

---

*SAGE is intended to become a lifelong intelligent companion under your complete control.*
