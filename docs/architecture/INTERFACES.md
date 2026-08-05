# SAGE Core Interfaces

All modules program to interfaces (Python `Protocol` or `ABC`). Implementations are swapped via the DI container.

This document is a human-readable summary. Source of truth: `sage/*/interfaces.py` and `sage/core/module.py`.

---

## Lifecycle — `SageModule`

Every major subsystem implements:

```python
class SageModule(Protocol):
    @property
    def name(self) -> str: ...
    @property
    def version(self) -> str: ...
    @property
    def is_critical(self) -> bool: ...

    async def initialize(self) -> None: ...
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def shutdown(self) -> None: ...
    async def health(self) -> HealthStatus: ...
```

---

## Event Bus

```python
class EventBus(Protocol):
    async def publish(self, event: Event) -> None: ...
    def subscribe(self, event_type: str, handler: EventHandler) -> Subscription: ...
    def unsubscribe(self, subscription: Subscription) -> None: ...
```

---

## Memory System

```python
class MemorySystem(Protocol):
    async def store(self, item: MemoryItem) -> str: ...
    async def recall(self, query: str, *, limit: int = 10, types: Sequence[MemoryType] | None = None) -> list[MemoryItem]: ...
    async def get(self, memory_id: str) -> MemoryItem | None: ...
    async def update(self, memory_id: str, **fields: Any) -> MemoryItem: ...
    async def forget(self, memory_id: str, *, reason: str = "") -> bool: ...
    async def consolidate(self) -> ConsolidationReport: ...
```

Memory types: `SHORT_TERM`, `LONG_TERM`, `EPISODIC`, `SEMANTIC`, `PREFERENCE`, `PROJECT`, `TECHNICAL`, `RELATIONSHIP`, `FACT`.

---

## Knowledge Manager

```python
class KnowledgeManager(Protocol):
    async def ingest(self, path: Path | str, *, category: str | None = None) -> DocumentRef: ...
    async def search(self, query: str, *, limit: int = 10) -> list[KnowledgeHit]: ...
    async def summarize(self, document_id: str) -> str: ...
    async def categorize(self, document_id: str) -> list[str]: ...
    async def relate(self, source_id: str, target_id: str, relation: str) -> None: ...
```

---

## Reasoning Engine

```python
class ReasoningEngine(Protocol):
    async def reason(
        self,
        problem: str,
        *,
        context: ReasoningContext | None = None,
        strategy: StrategyKind = StrategyKind.AUTO,
    ) -> ReasoningResult: ...
```

`ReasoningResult` always includes an explainable `trace: list[ReasoningStep]`.

---

## Learning Engine

```python
class LearningEngine(Protocol):
    async def observe(self, observation: Observation) -> None: ...
    async def learn_preference(self, key: str, value: Any, *, confidence: float = 0.5) -> None: ...
    async def get_preference(self, key: str) -> Preference | None: ...
    async def refine(self, feedback: Feedback) -> None: ...
```

---

## Planning Engine

```python
class PlanningEngine(Protocol):
    async def create_goal(self, description: str, **kwargs: Any) -> Goal: ...
    async def plan(self, goal_id: str) -> Plan: ...
    async def prioritize(self, task_ids: Sequence[str]) -> list[str]: ...
    async def track(self, plan_id: str) -> PlanStatus: ...
```

---

## Agents

```python
class Agent(Protocol):
    @property
    def id(self) -> str: ...
    @property
    def domain(self) -> str: ...
    @property
    def capabilities(self) -> frozenset[str]: ...

    async def can_handle(self, task: AgentTask) -> float: ...  # confidence 0..1
    async def execute(self, task: AgentTask) -> AgentResult: ...

class AgentOrchestrator(Protocol):
    async def dispatch(self, task: AgentTask) -> AgentResult: ...
    async def collaborate(self, task: AgentTask, agent_ids: Sequence[str]) -> AgentResult: ...
```

---

## Plugins

```python
class Plugin(Protocol):
    @property
    def manifest(self) -> PluginManifest: ...

    async def on_load(self, container: Container) -> None: ...
    async def on_unload(self) -> None: ...
```

---

## Tools

```python
class Tool(Protocol):
    @property
    def name(self) -> str: ...
    @property
    def description(self) -> str: ...
    @property
    def parameters_schema(self) -> dict[str, Any]: ...

    async def execute(self, **params: Any) -> ToolResult: ...

class ToolManager(Protocol):
    def register(self, tool: Tool) -> None: ...
    async def invoke(self, name: str, **params: Any) -> ToolResult: ...
    def list_tools(self) -> list[ToolInfo]: ...
```

---

## Conversation

```python
class ConversationEngine(Protocol):
    async def start_session(self, *, user_id: str = "default") -> Session: ...
    async def respond(self, session_id: str, message: str) -> ConversationTurn: ...
    async def end_session(self, session_id: str) -> None: ...
```

---

## Model Adapters

```python
class LanguageModel(Protocol):
    @property
    def provider(self) -> str: ...
    @property
    def model_name(self) -> str: ...

    async def complete(self, request: CompletionRequest) -> CompletionResponse: ...

class EmbeddingModel(Protocol):
    async def embed(self, texts: Sequence[str]) -> list[list[float]]: ...

class ModelRouter(Protocol):
    def get_language_model(self, *, capability: str | None = None) -> LanguageModel: ...
    def get_embedding_model(self) -> EmbeddingModel: ...
```

---

## File Manager

```python
class FileManager(Protocol):
    async def index(self, path: Path) -> FileRecord: ...
    async def search(self, query: str) -> list[FileRecord]: ...
    async def watch(self, directory: Path) -> None: ...
```

---

## Design notes

1. **Async by default** — I/O and model calls never block the event loop.  
2. **Pure data models** — Pydantic/`dataclass` for all DTOs crossing boundaries.  
3. **No circular imports** — interfaces live in `interfaces.py`; services import interfaces, not concrete peers.  
4. **Result objects over exceptions** for expected domain failures; exceptions for truly exceptional cases.  
