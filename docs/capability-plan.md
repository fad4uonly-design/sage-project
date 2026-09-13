# SAGE Capability Implementation Plan

## Phase 1 — Finish what's half-built (do first, unblocks everything)

### 1. TurboVec — real embeddings behind EmbeddingModel
**Gap**: MemoryStore.insert() writes to DB but never populates SqliteVectorIndex.
Semantic recall searches an empty index. Embedding models + index exist but aren't wired.
**Fix**: Wire vector index into memory store path so embeddings are indexed on write.

### 2. Tool-R0 — verify-then-answer gate
**Gap**: No verification layer between tool execution and final answer.
**Fix**: Build verification gate that validates tool outputs against schemas/evidence before answering.

### 3. RAGforge — surface per-layer confidence as citations
**Gap**: Retrieval pipeline computes per-layer confidence but never surfaces it as citations.
**Fix**: Build citation formatter that turns RetrievalResult evidence into structured citations.

## Phase 2 — Self-improvement loop (Ornith exists; extend it)
4. Evolver — variant iteration on top of improvement.ts
5. SOUP — cheap experiment comparison before adopting a variant
6. NNsight introspection — extend MIE inspectors for explainable Evolver decisions

## Phase 3 — Model bench
7. Add GPT-2 Small, OpenELM, OLMo 3, SmolLM2, Qwen2.5, Qwen3 + TinyStories eval
   to the Pythia research harness.

## Phase 4 — Genuinely new capabilities (biggest scope, do last)
8. SmolVLM -> VisionModel protocol (image understanding)
9. Whisper Tiny -> AudioTranscriber protocol (speech input)
10. TurboQuant/vLLM/llama.cpp/Ollama -> RuntimePlugin registry
    (serving/quantization choice never touches app code)