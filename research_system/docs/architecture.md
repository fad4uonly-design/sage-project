# SAGE Research System — Architecture & Boundaries

This document is the architectural contract for the Research SAGE / Model Lab.
It records both what is built and what is deliberately **not** built, so the
module stays independently testable, packageable, and later integrable into
`D:\sage` without rewriting its internal research logic.

---

## 1. Boundary: Research SAGE / Model Lab only

**In scope (Research SAGE / Model Lab):**

- loading models in their original format
- architecture inspection and mapping
- behavioral / activation / representation / causal research (later milestones)
- experiment records, mechanism graph, knowledge layers 1–3

**Out of scope — must NOT be implemented here:**

| Concern | Where it belongs |
|---|---|
| production SAGE mutation | later stage, outside this package |
| autonomous self-rewriting | later stage |
| candidate production upgrades | later stage |
| model fine-tuning | later stage |
| weight copying into SAGE | later stage |
| automatic production integration | later stage / MIE |

The module is a **pure consumer of normalized model capabilities**. It is
written so the eventual SAGE integration happens through the existing Model
Integration Engine contracts: MIE adapts whatever runtime it manages to the
`LoadedModel` port defined here.

---

## 2. The five knowledge layers

| Layer | Name | Status for this milestone |
|---|---|---|
| 1 | Model Knowledge | **Active** — produced by architecture inspection |
| 2 | Mechanism Knowledge | Active vocabulary (graph scaffolding); not yet populated |
| 3 | Research Knowledge | Active vocabulary; not yet populated |
| 4 | Engineering Knowledge | Dormant |
| 5 | SAGE Self-Knowledge | Dormant |

`KnowledgeLayer` in `domain/knowledge.py` encodes all five; the inspection
experiment only ever produces Layer-1 records.

---

## 3. The three uncertainty domains

1. **Model uncertainty** — identity/version/provenance and measurement fidelity.
2. **Method uncertainty** — whether the method measures what it claims.
3. **SAGE uncertainty** — dormant for Specimen 001; omitted from profiles so it
   never spuriously lowers confidence.

**Invariant:** *confidence must never exceed the weakest dependency.*

Implemented in two places:

- `UncertaintyProfile.ceiling` = minimum over the domains a claim depends on.
- `cap_confidence(profile, dependency_confidences)` = min(ceiling, weakest
  dependency record). `KnowledgeRecord.__post_init__` rejects any confidence
  above the domain ceiling; the knowledge builder caps by dependency confidence.

A dormant domain is simply absent from the profile (and `get()` returns 1.0),
so it does not constrain the claim.

---

## 4. Mechanism graph contract (Layer 2)

The graph vocabulary (`domain/mechanism.py`) already encodes the rules; no
population/analysis logic exists yet.

- **Node kinds:** `Component`, `Mechanism`, `Capability`, `Behavior`,
  `Representation`, `Transformation` — kept distinct so a component is never
  fused with a function.
- **Scope:** `ModelSpecific` vs `Abstract` — model-specific mechanisms and
  abstract mechanisms remain distinct.
- **Edges:** many-to-many, always carrying an `EvidenceRef`. The evidence
  **category** decides whether an edge may be treated as causal. A
  `correlates_with` edge backed by correlational evidence is never causation.
- **One component → one function is forbidden** by construction: nothing in the
  data model enforces or assumes a 1:1 mapping, and `edges_between(a, b)`
  returns all edges, not one.

Evidence categories (also in `domain/knowledge.py`): `architecture`, `behavior`,
`representation`, `transformation`, `causal`, `correlational`. Representation,
transformation, and causal contribution are separate categories.

---

## 5. Knowledge states

`confirmed`, `replicated`, `strong_evidence`, `weak_evidence`, `hypothesis`,
`unknown`, `failed_prediction`, `contested`.

Every `KnowledgeRecord` also tracks:

- replication status
- generalization state
- evidence sources
- counterevidence
- dependency chain (`dependencies`)
- confidence ceiling (`uncertainty.ceiling`)

States that assert something observed (`confirmed`, `replicated`,
`strong_evidence`, `weak_evidence`) require at least one evidence reference.

---

## 6. Capability stack

1. Model Inspection
2. Behavioral Research
3. Activation Research
4. Representation Research
5. Causal Research
6. Mechanistic Research
7. Engineering *(dormant)*
8. Self-Improvement *(dormant)*

The stack is **not** a linear workflow; all levels remain conceptually
available. Specimen 001 implements level 1; levels 2–6 plug in later without
restructuring the foundation (new experiments implement new ports/commands and
reuse `LoadedModel`, the knowledge layer, and the mechanism graph).

---

## 7. Research loop (structure only, not yet executed)

```
Knowledge Boundary → Research Question → Question Classification
→ Method Selection → Expected Information Gain → Experiment Design → Execution
→ Result Classification → Evidence Assignment → Mechanism Graph Update
→ Knowledge Boundary Update → Actual vs Expected Information Gain
→ Method Performance Update → Research Lesson → next question
```

This milestone only executes the linear slice *artifact → load → inspect →
map → knowledge record*. The full loop, experiment-record schema, and
method-evidence ledger are later milestones; the vocabulary they need is
already present.

---

## 8. Dependency & layer rules

```
domain/        (pure data, invariants, enums)        ← imports nothing
interfaces/    (protocols + ABCs)                    ← imports domain only
infrastructure/ (runtime + persistence adapters)     ← imports domain + interfaces
experiments/   (research procedures)                 ← imports domain + interfaces
```

Hard rules:

1. `domain` never imports `torch`, `transformers`, `infrastructure`, or
   `experiments`.
2. `infrastructure/pytorch_loader.py` is the **only** module allowed to import
   `torch`/`transformers`, and does so lazily inside `load()`.
3. No hidden global state: every experiment, loader, inspector, and repository
   is an explicit object with injected dependencies and an injectable clock.
4. Evidence-bearing values are immutable (frozen dataclasses, tuples,
   `ImmutableMap`); ids are content-addressed for determinism.
5. No model-specific business logic in core domain structures — heuristics
   (e.g. naming-based component classification) live in the inspector.

---

## 9. Extension guide (later milestones)

- **Behavioral research** — add a `BehaviorExperiment` under `experiments/`,
  consuming `LoadedModel` (extend the protocol with `forward()` if needed) and
  writing Layer-2 records + a `Behavior` mechanism-graph node.
- **Activation capture** — add a hook port (e.g. `ActivationCapture`) returning
  normalized tensors; do not import torch in domain.
- **Ablation / patching** — add `CausalExperiment`s whose evidence carries
  `EvidenceCategory.CAUSAL`; only these may add causal edges.
- **Research loop / method ledger** — a `ResearchLoop` orchestrator that emits
  `ResearchQuestion`, `Prediction`, and `MethodPerformance` records (Layer 3).

Each addition is additive: new experiment modules + new ports, no changes to
existing domain types.
