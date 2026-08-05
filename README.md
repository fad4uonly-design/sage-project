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
├── Core Engine          # Boot, DI, lifecycle, health, coordination
├── Event Bus            # Loose coupling between modules
├── Memory System        # Short/long-term, episodic, semantic
├── Knowledge Manager    # Document ingestion & knowledge graph
├── Reasoning Engine     # Deduction, induction, multi-step logic
├── Learning Engine      # Pattern recognition, preference learning
├── Planning Engine      # Goals, schedules, workflows
├── Agent Framework      # Specialized collaborative agents
├── Plugin System        # Extensibility without core changes
├── Tool Manager         # Python, Git, SQLite, APIs, CLI
├── Conversation Engine  # Context-aware multi-turn dialogue
├── File Manager         # Indexing, watching, categorization
├── API Layer            # Programmatic access
└── User Interface       # CLI → Desktop → Web → Voice → Mobile
```

Modules communicate through the **Event Bus** and are coordinated by the **Core Engine**. Each module is independently testable and follows clean architecture / SOLID principles.

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

# Run tests
pytest
```

---

## Development Roadmap

| Phase | Focus | Status |
|---|---|---|
| **0** | Architecture, interfaces, folder structure, startup | ✅ Current |
| **1** | Foundation — Core, Memory, Database, Config | 🔜 Next |
| **2** | Intelligence — Knowledge, Reasoning, Learning, Planning | Planned |
| **3** | Automation — Agents, Plugins, Event Bus, Tools | Planned |
| **4** | UX — Desktop, Web, Voice, Mobile | Planned |
| **5** | Advanced — Multi-agent, autonomous workflows, predictive | Planned |

See [docs/architecture/OVERVIEW.md](docs/architecture/OVERVIEW.md) for the full design.

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
│   ├── core/             # Core Engine, bootstrap, DI container
│   ├── config/           # Configuration manager
│   ├── events/           # Event bus
│   ├── memory/           # Memory system
│   ├── knowledge/        # Knowledge manager
│   ├── reasoning/        # Reasoning engine
│   ├── learning/         # Learning engine
│   ├── planning/         # Planning engine
│   ├── agents/           # Agent framework
│   ├── plugins/          # Plugin manager
│   ├── tools/            # Tool manager
│   ├── conversation/     # Conversation engine
│   ├── files/            # File manager
│   ├── db/               # Database layer
│   ├── models/           # AI model adapters
│   ├── api/              # API layer
│   ├── ui/               # User interfaces
│   ├── logging/          # Structured logging
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
