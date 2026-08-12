# First Vertical Slice Validation Plan — Ollama Deployment

**Fixture requested by project:** `Qwen3 4B Thinking 2507`
**Runtime reference supplied:** `qwen3:4b`
**Status:** plan only; no local runtime/model evidence collected in Phase 1

This named case validates the generic engine. It does not define the architecture and must not introduce a Qwen branch in core source.

## 1. Identity caution

The supplied human name and runtime tag are not sufficient to prove an exact revision. The public Ollama page for `qwen3:4b` currently describes a Qwen3 4.02B, Q4_K_M artifact and labels tools/thinking, but that is provider metadata—not proof of what a particular local tag resolves to.[1] The local `GET /api/tags` digest and `POST /api/show` response must anchor the tested deployment.[2][3]

Until inspection reconciles model metadata, digest, and any upstream revision, the phrase “Thinking 2507” remains an **unverified identity assertion supplied by the user**. The engine must not silently rewrite the requested tag to another tag.

## 2. Preconditions

- User explicitly authorizes read-only access to one Ollama endpoint.
- Ollama is already running; the engine does not start/stop it in this slice.
- `qwen3:4b` is already installed; the engine does not pull/create/copy/delete it.
- A sandbox backend can allowlist only that endpoint for inference tests.
- Resource/time/output limits are configured.
- A synthetic target profile is used; SAGE is not accessed.

If any precondition is missing, produce a partial package with a structured blocker.

## 3. Generic workflow

### Stage A — runtime discovery

1. `GET /api/version`
2. Record endpoint locality, version, response digest, timestamp, and collector version.
3. `GET /api/tags`
4. Select exact configured model reference as data (`qwen3:4b`).
5. Record returned name, model, size, digest, format, family labels, parameter-size label, quantization label, and unknown fields.

Expected evidence levels: `DETECTED_FROM_RUNTIME`. No behavioral capability is validated.

### Stage B — inspection

1. `POST /api/show` with `model: qwen3:4b`, first non-verbose and then verbose if policy/size permits.
2. Capture:
   - template and its digest;
   - runtime-declared capabilities;
   - license digest/reference;
   - parameter text;
   - details and all `model_info` keys;
   - architecture, tokenizer, context, quantization, and parameter findings;
   - modified timestamp and response digest.
3. Reconcile `/api/tags` and `/api/show` identity data.
4. Preserve unknown architecture-specific metadata without writing a family parser.
5. Build template/tokenizer/architecture descriptions from generic key patterns and raw key/value bags.

Expected levels: `DETECTED_FROM_METADATA` for model metadata fields and `DETECTED_FROM_RUNTIME` for endpoint behavior/declarations. Provider-page facts stay `PROVIDER_DOCUMENT`/inferred and separate.

### Stage C — initial hypotheses

Generic detectors may propose:

- text generation;
- runtime streaming;
- runtime structured-output request handling;
- runtime tool-definition request handling;
- separately exposed thinking field;
- declared context maximum;
- instruction/reasoning/tool behavior hypotheses.

All are unvalidated until their exact subject behavior is tested. No vision/audio/embedding/coding/planning claim is created merely from model family or absence/presence of broad tags.

### Stage D — adapter resolution

The planner should find/configure a generic Ollama runtime adapter:

- endpoint + exact deployment reference;
- chat endpoint;
- runtime-owned template by default;
- non-stream and NDJSON stream normalization;
- optional `format`, `tools`, and `think` fields when the runtime contract supports them;
- response mapping for content, thinking, tool calls, usage, durations, done reason, and errors.

If new source is generated instead of configuring this generic adapter, the plan must explain which protocol gap required generation. Generated source remains untrusted.

### Stage E — sandboxed probes

Run bounded, non-consequential tests:

1. **Basic inference:** nonce echo/transformation with strict output cap.
2. **Instruction following:** exact structured transformation across two turns.
3. **Streaming:** parse stream to terminal event; compare assembled semantic output shape.
4. **Structured output:** request a small JSON Schema, validate syntax and schema over repeated trials.
5. **Tool calling:** offer one fake deterministic function, verify exact function/argument object, return a fake result, and verify final response. Do not execute real tools.
6. **Thinking channel:** request supported thinking mode and verify protocol separation/normalization only. Do not retain or grade private reasoning text unless policy explicitly allows it.
7. **Reasoning outcome:** generated small exact-answer problems; score final answers only.
8. **Context ladder:** safe increasing prompts with retrieval canaries, capped well below resource limits; validate only the largest successful tested size.
9. **Failure behavior:** unknown model reference, malformed schema/tool definition, timeout/cancellation, and interrupted stream against fakes where live disruption would be unsafe.
10. **Recovery:** a normal request after a handled failure.

The official chat API exposes request concepts for messages, tools, structured `format`, streaming, images, and thinking, and response concepts for content, thinking, tool calls, usage, and finish data.[4] That documents the runtime contract; each local deployment behavior still requires probing.

### Stage F — compatibility and package

- Evaluate exact synthetic target requirements.
- Separate direct support from adapter-provided support.
- Calculate capability delta against an empty/synthetic baseline only for the slice.
- Include all unknowns, contradictions, limits, risks, permission requests, and sandbox controls.
- Produce a schema-valid package in `PROPOSED` or `AWAITING_APPROVAL`.
- Stop. No integration or active registry update.

## 4. Evidence matrix

| Candidate statement | Subject | Minimum evidence to state | Minimum evidence to validate |
|---|---|---|---|
| Artifact format is GGUF | Deployment/artifact | Local tags/show metadata | Consistent local observations; optional direct artifact header later |
| Architecture label | Artifact/model | Local `model_info` | Metadata fact only; no behavior implied |
| Runtime supports streaming transport | Runtime | API declaration | Successful protocol stream test |
| Deployment generates text | Model deployment | Runtime declaration/hypothesis | Successful basic inference tests |
| Runtime accepts JSON Schema format | Runtime | API contract/local probe | Successful request/response contract test |
| Model follows schema reliably | Model deployment | Hypothesis | Repeated schema-valid outputs under recorded profile |
| Runtime accepts tools | Runtime | API contract/local probe | Successful tools request contract test |
| Model uses tools reliably | Model deployment | Metadata hypothesis | Repeated correct fake tool calls and result handling |
| Thinking is separately exposed | Runtime + deployment | Local declaration | Response-channel protocol test |
| Context length is N | Artifact/runtime | Metadata declaration | Metadata remains declared; behavioral tested limit is separately recorded |
| Reasoning capability | Model deployment | Inference/provider declaration | Versioned exact-answer suite threshold |
| Coding/planning/etc. | Model deployment | Hypothesis only | Capability-specific suite threshold |

## 5. Failure rules

- Runtime unreachable: stop discovery with retryable blocker.
- Tag absent: do not pull it; produce `MODEL_REFERENCE_NOT_FOUND`.
- Digest changes during run: invalidate observations and restart with new deployment identity.
- Show response lacks a field: keep it unknown.
- Runtime advertises a feature but probe fails: preserve both records and mark conflicting/partial.
- Sandbox lacks mandatory isolation: do not run generated code/live probes that exceed policy.
- Test times out/errors: record inconclusive/error, not unsupported by default.
- Template parse fails: runtime-owned templating may still be testable, but static template compatibility remains unknown and risk is reported.

## 6. Slice deliverables

- runtime/deployment discovery records;
- inspection report and evidence bundle;
- capability hypotheses and validated claims;
- compatibility assessment against synthetic profile;
- generic Ollama adapter configuration/candidate;
- sandbox attestation and evaluation runs;
- draft integration package;
- phase report listing what worked, evidence, remaining work, and unverified assumptions.

## 7. Unverified assumptions before execution

- The endpoint is available and compatible with documented API semantics.
- The local `qwen3:4b` tag exists.
- The local digest corresponds to the intended “Thinking 2507” artifact.
- Runtime-reported metadata is complete and internally consistent.
- Required sandbox controls are available in the execution environment.
- Hardware resources are sufficient for bounded tests.
- A generic Ollama adapter can cover the deployment without generated code.
- Behavioral thresholds and synthetic target profile have been approved for validation purposes.

## 8. References

1. Ollama library, [`qwen3:4b`](https://ollama.com/library/qwen3:4b).
2. Ollama, [List models API](https://docs.ollama.com/api/tags.md).
3. Ollama, [Show model details API](https://docs.ollama.com/api-reference/show-model-details.md).
4. Ollama, [Chat API](https://docs.ollama.com/api/chat.md).
