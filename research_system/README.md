# SAGE Research System — Model Lab

An independent, packageable scientific research system that studies AI models
and records evidence about their mechanisms.

> **Research Specimen 001 — Pythia-70M**
> This milestone implements the foundation slice only:
>
> `Model artifact → model loading boundary → architecture inspection → architecture map → Model Knowledge record → tests`
>
> Later milestones (behavioral, activation, representation, causal research)
> plug into the same interfaces without restructuring this foundation.

---

## Architectural boundary (read this first)

This module is the **Research SAGE / Model Lab only**. It deliberately does **NOT**
implement, and must never be extended here to implement:

- production SAGE mutation
- autonomous self-rewriting
- candidate production upgrades
- model fine-tuning
- weight copying into SAGE
- automatic production integration

Those belong to later stages of SAGE and live outside this package. The eventual
integration into `D:\sage` goes through the existing **Model Integration Engine
contracts**: this package only *consumes normalized model capabilities* and never
couples to Ollama, GGUF, Qwen, Transformers internals, or any single runtime.

The full contract (five knowledge layers, three uncertainty domains, mechanism
graph rules, knowledge states, capability stack) is documented in
[`docs/architecture.md`](docs/architecture.md).

---

## Layout

```
src/sage_research/
├── domain/            # pure data + invariants (no I/O, no runtime imports)
│   ├── collections.py     # ImmutableMap
│   ├── confidence.py      # Confidence, 3 uncertainty domains, ceiling rule
│   ├── knowledge.py       # knowledge states, evidence, KnowledgeRecord
│   ├── model_artifact.py  # ModelArtifact, ModelIdentity, LoadOptions
│   ├── architecture_map.py# Component / Connection / ModelSummary / ArchitectureMap
│   └── mechanism.py       # Layer-2 graph vocabulary (scaffolding, unpopulated)
├── interfaces/        # ports (MIE/ARENA boundary)
│   ├── model_loader.py    # LoadedModel protocol + ModelLoader
│   ├── inspector.py       # ArchitectureInspector
│   └── repository.py      # KnowledgeRepository
├── infrastructure/    # runtime + persistence adapters
│   ├── pytorch_loader.py  # the ONLY place torch/transformers are imported (lazily)
│   ├── json_repository.py # atomic JSON-file knowledge store
│   └── in_memory_repository.py
├── experiments/       # research execution
│   ├── architecture_inspector.py # normalized model -> ArchitectureMap
│   ├── model_knowledge.py        # ArchitectureMap -> Layer-1 records
│   └── inspection.py             # the inspection experiment + report
└── cli.py             # `sage-research inspect ...`
```

Dependency rule: `domain` ← `interfaces` ← `infrastructure`/`experiments`.
`domain` never imports anything from `infrastructure` or `experiments`, and
never imports `torch`/`transformers`.

---

## Install

```bash
# Core (zero runtime dependencies — research layer only):
pip install -e .

# For the real Pythia-70M inspection path (torch + transformers):
pip install -e ".[pytorch]"

# Development (pytest):
pip install -e ".[pytorch,dev]"
```

Python ≥ 3.10 required.

---

## Usage

```bash
# Full inspection of the real Pythia-70M (downloads ~150 MB on first run):
sage-research inspect --model EleutherAI/pythia-70m --output ./out

# Or as a module:
python -m sage_research inspect --model EleutherAI/pythia-70m
```

Outputs into `--output`:

- `architecture_map.json` — the structured architecture map
- `inspection_report.json` — the immutable inspection report (environment,
  rerun configuration, records)
- `knowledge/<knowledge_id>.json` — one file per Model Knowledge record

Python API:

```python
from sage_research.domain.model_artifact import ModelArtifact
from sage_research.experiments import HeuristicArchitectureInspector, ModelInspectionExperiment
from sage_research.infrastructure import InMemoryKnowledgeRepository, PyTorchModelLoader

experiment = ModelInspectionExperiment(
    loader=PyTorchModelLoader(),
    inspector=HeuristicArchitectureInspector(),
    repository=InMemoryKnowledgeRepository(),
)
report = experiment.run(ModelArtifact(name="pythia-70m"))
print(report.architecture_map.summary.total_parameters)
```

---

## Tests

```bash
pytest                                    # unit tests (fast, deterministic, no torch)
pytest -m integration                     # real Pythia-70M path (torch + network)
```

- **Unit tests** run against a tiny deterministic fake model (`tests/helpers.py`)
  and never touch the network or a runtime. They verify the domain invariants
  (confidence ≤ weakest dependency, immutable evidence, deterministic ids) and
  the full inspection pipeline.
- **Integration tests** load `EleutherAI/pythia-70m` and verify the known
  architecture (`6 layers, hidden 512, vocab 50304, 8 heads, ~70M params`).
  They skip cleanly when `torch`/`transformers` or the network is unavailable.

---

## Key invariants enforced in code

1. **Confidence never exceeds the weakest dependency** — `KnowledgeRecord`
   rejects any confidence above its uncertainty ceiling; `cap_confidence`
   additionally caps by every dependency's confidence.
2. **Evidence is immutable** — frozen dataclasses, tuples, and `ImmutableMap`;
   `Confirmed`/`Replicated`/`Strong`/`Weak` states require at least one
   evidence reference.
3. **Determinism** — knowledge ids are content-addressed (`sha256`), report ids
   are stable given the same clock, and there is no hidden global state.
4. **No model-specific logic in core domain** — classification heuristics live
   in the inspector (application layer), not in the domain types.
5. **Correlation ≠ causation** — architecture-map connections are structural
   only; causal claims require causal evidence in the (future) mechanism graph.

## What is intentionally NOT here yet

Behavioral experiments, activation capture, representation/probing, ablation,
activation patching, the research loop, method-evidence tracking, and the
populated mechanism graph are **later milestones**. Their data vocabulary
(knowledge states, evidence categories, mechanism node/edge types) is already
present so the foundation never needs restructuring — see
[`docs/architecture.md`](docs/architecture.md).
