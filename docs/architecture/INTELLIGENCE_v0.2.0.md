# SAGE v0.2.0 — Intelligence Layer

**Status:** Implemented  
**Builds on:** v0.1.1 Core Foundation

---

## Goal

Evolve SAGE from a modular application into a **knowledge-centric AI operating system** with:

1. Knowledge Graph (semantic foundation)
2. Reasoning Strategy Framework
3. Layered Retrieval Intelligence
4. Learning enhancements
5. Explainable reasoning traces
6. Capability Registry (future-proofing for domain agents)

---

## 1. Knowledge Graph (`sage.knowledge.graph`)

SQLite-backed graph with versioning, confidence, provenance, and bidirectional edges.

```
Tomato
 ├── is_a → Crop
 ├── requires → Water
 ├── grows_in → Warm Climate
 ├── affected_by → Blight
 └── harvested_after → 90 Days
```

### Features
- Entity upsert with canonical-name dedup
- Typed entities (`crop`, `process`, `condition`, …)
- Typed relations (`is_a`, `requires`, `grows_in`, …)
- Rule-based entity/relation extraction
- Mentions linking entities → documents/memories
- Entity version history
- Path finding (BFS)
- Subgraph expansion
- Seed core ontology on boot
- Document ingest auto-extracts into the graph

### Tables
`kg_entities`, `kg_edges`, `kg_entity_versions`, `kg_edge_versions`, `kg_mentions`

---

## 2. Reasoning Strategy Framework

Specialized strategies replace one-size-fits-all reasoning:

| Strategy | Use |
|---|---|
| Logical / Deduction | Premises → conclusions |
| Induction | Patterns from observations |
| Mathematical | Quantities, expressions |
| Scientific | Hypothesis / evidence |
| Business | Unit economics, options |
| Agriculture | Season, soil, water, pests |
| Planning | WBS / sequencing |
| Risk | Likelihood × impact |
| Decision | Multi-criteria choice |
| Ethical | Stakeholders / harm |
| Causal | Root cause chains |
| Multi-step | General decomposition |

Orchestrator/engine **selects by suitability score** (keywords + domain context).  
Multiple strategies can be fused. Every result includes an **ExplainabilityReport**.

---

## 3. Retrieval Intelligence (`sage.retrieval`)

Layered pipeline:

```
1. Memory search
2. Knowledge graph lookup
3. Document retrieval
4. Semantic search (embeddings / stub)
5. Learned patterns
6. Context ranking + confidence scoring
```

Used by Orchestrator (`RETRIEVE` step) and Reasoning Engine (auto-enrich).

---

## 4. Learning Enhancements

- Recurring pattern detection (workflows, domain interest, preference cues)
- Confidence refinement via feedback
- Graph relationship suggestions from observations
- `find_patterns()` for retrieval layer

---

## 5. Explainable Reasoning

```
Question
↓ Relevant Memories
↓ Knowledge Graph Facts
↓ Supporting Documents
↓ Reasoning Strategy
↓ Confidence Score
↓ Final Answer
```

`ExplainabilityReport.format()` produces a human-readable markdown trace.  
Reason intents return this full report.

---

## 6. Capability Registry (`sage.capabilities`)

Agents/tools declare:

- Domains
- Capabilities
- Tools
- Required permissions
- Preferred reasoning strategies
- Confidence thresholds

Built-in descriptors include future domain agents (agriculture, finance, business, programming) marked `status: declared` for v0.3 implementation.  
Agent dispatch boosts scores using registry matches.

---

## Boot order (v0.2.0)

```
database → secrets → permissions → config → memory
→ knowledge (graph) → models → retrieval → reasoning → learning
→ planning → tools → capabilities → agents → plugins → files
→ orchestrator → monitor → conversation
```

---

## Schema

Migration **v3** (`intelligence_v020`).

---

## Next (v0.3.0)

Domain Intelligence — implement full Agriculture, Finance, Accounting, Business, and Programming agents against the Capability Registry and Knowledge Graph.
