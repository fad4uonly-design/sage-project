# SAGE Folder Structure

```
sage/                              # Repository root
│
├── pyproject.toml                 # Package metadata, deps, tool config
├── README.md
├── LICENSE
├── .env.example
├── .gitignore
│
├── sage/                          # Installable Python package
│   ├── __init__.py                # Package version, public exports
│   ├── py.typed                   # PEP 561 marker
│   ├── cli.py                     # Typer CLI entry (sage start|status|ask)
│   │
│   ├── core/                      # ★ Core Engine
│   │   ├── __init__.py
│   │   ├── engine.py              # SageEngine — central coordinator
│   │   ├── bootstrap.py           # Ordered startup / shutdown
│   │   ├── container.py           # DI container
│   │   ├── module.py              # Module base class + lifecycle protocol
│   │   ├── registry.py            # Module registry
│   │   ├── health.py              # Health checks & status
│   │   └── scheduler.py           # Background job scheduler
│   │
│   ├── config/                    # Configuration
│   │   ├── __init__.py
│   │   ├── settings.py            # Pydantic settings model
│   │   ├── loader.py              # YAML + env loader
│   │   └── defaults.yaml          # Default configuration
│   │
│   ├── events/                    # Event Bus
│   │   ├── __init__.py
│   │   ├── bus.py                 # EventBus implementation
│   │   ├── events.py              # Base event types
│   │   └── types.py               # Domain event dataclasses
│   │
│   ├── db/                        # Database layer
│   │   ├── __init__.py
│   │   ├── connection.py          # Connection manager
│   │   ├── repository.py          # Base repository
│   │   ├── migrations.py          # Simple migration runner
│   │   └── schema.sql             # Initial schema
│   │
│   ├── memory/                    # Memory System
│   │   ├── __init__.py
│   │   ├── interfaces.py          # Memory protocols
│   │   ├── models.py              # MemoryItem, MemoryType, etc.
│   │   ├── store.py               # Persistence
│   │   ├── retriever.py           # Query / rank / recall
│   │   ├── consolidator.py        # Dedup & merge
│   │   └── service.py             # MemorySystem façade
│   │
│   ├── knowledge/                 # Knowledge Manager
│   │   ├── __init__.py
│   │   ├── interfaces.py
│   │   ├── models.py
│   │   ├── ingest.py              # Document parsers pipeline
│   │   ├── categorizer.py
│   │   ├── graph.py               # Relationships
│   │   ├── search.py
│   │   └── service.py
│   │
│   ├── reasoning/                 # Reasoning Engine
│   │   ├── __init__.py
│   │   ├── interfaces.py
│   │   ├── models.py              # ReasoningTrace, Step, Conclusion
│   │   ├── engine.py
│   │   └── strategies.py          # Deduction, induction, etc.
│   │
│   ├── learning/                  # Learning Engine
│   │   ├── __init__.py
│   │   ├── interfaces.py
│   │   ├── models.py
│   │   ├── engine.py
│   │   └── observers.py           # Listen to events & learn
│   │
│   ├── planning/                  # Planning Engine
│   │   ├── __init__.py
│   │   ├── interfaces.py
│   │   ├── models.py              # Goal, Plan, Task
│   │   └── engine.py
│   │
│   ├── agents/                    # Agent Framework
│   │   ├── __init__.py
│   │   ├── interfaces.py
│   │   ├── base.py                # BaseAgent
│   │   ├── registry.py
│   │   ├── orchestrator.py
│   │   └── builtin/               # Built-in agents (later)
│   │       └── __init__.py
│   │
│   ├── plugins/                   # Plugin System
│   │   ├── __init__.py
│   │   ├── interfaces.py
│   │   ├── manager.py
│   │   ├── loader.py
│   │   └── manifest.py            # Plugin manifest schema
│   │
│   ├── tools/                     # Tool Manager
│   │   ├── __init__.py
│   │   ├── interfaces.py
│   │   ├── manager.py
│   │   ├── base.py
│   │   └── builtin/               # Built-in tools (later)
│   │       └── __init__.py
│   │
│   ├── conversation/              # Conversation Engine
│   │   ├── __init__.py
│   │   ├── interfaces.py
│   │   ├── models.py
│   │   ├── engine.py
│   │   ├── context.py
│   │   └── personality.py
│   │
│   ├── files/                     # File Manager
│   │   ├── __init__.py
│   │   ├── interfaces.py
│   │   ├── manager.py
│   │   └── watcher.py
│   │
│   ├── models/                    # AI Model adapters
│   │   ├── __init__.py
│   │   ├── interfaces.py          # LanguageModel, EmbeddingModel
│   │   ├── router.py
│   │   ├── stub.py                # Offline stub
│   │   ├── openai_adapter.py      # Optional
│   │   └── anthropic_adapter.py   # Optional
│   │
│   ├── api/                       # API Layer (Phase 4)
│   │   └── __init__.py
│   │
│   ├── ui/                        # User interfaces
│   │   ├── __init__.py
│   │   └── cli_app.py             # Rich interactive shell
│   │
│   ├── logging/                   # Logging setup
│   │   ├── __init__.py
│   │   └── setup.py
│   │
│   └── utils/                     # Shared helpers
│       ├── __init__.py
│       ├── ids.py                 # ULID / UUID helpers
│       ├── time.py
│       └── result.py              # Result / Maybe helpers
│
├── tests/
│   ├── unit/
│   ├── integration/
│   └── fixtures/
│
├── docs/
│   ├── architecture/
│   ├── api/
│   └── guides/
│
├── data/                          # Runtime (contents gitignored)
│   ├── config/
│   ├── memory/
│   ├── knowledge/
│   └── logs/
│
├── plugins/                       # External plugins directory
├── scripts/                       # Dev scripts
└── examples/
```

## Naming conventions

| Kind | Convention | Example |
|---|---|---|
| Packages | `snake_case` | `sage.memory` |
| Modules (files) | `snake_case` | `consolidator.py` |
| Classes | `PascalCase` | `MemorySystem` |
| Interfaces/Protocols | `PascalCase` + descriptive | `MemoryStore`, `LanguageModel` |
| Functions / methods | `snake_case` | `recall_similar` |
| Events | `domain.entity.action` | `memory.item.created` |
| Constants | `UPPER_SNAKE` | `DEFAULT_IMPORTANCE` |
