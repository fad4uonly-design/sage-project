# Model Integration Engine (MIE)

A standalone, evidence-first engine for discovering, inspecting, evaluating, proposing, approving, and safely staging model integrations. It is intended to become an input to SAGE later, but **this repository neither imports nor modifies SAGE**.

## Current status

**Part 3 — production-oriented generic lifecycle infrastructure implemented.**

Default workflow:

```text
discover → inspect → reconcile identity → hypothesize capabilities
→ sandbox-bound probes → validate → compatibility → adapter resolution
→ security assessment → immutable proposed package → approval request → STOP
```

Terminal state:

```text
DRAFT_PENDING_APPROVAL
```

Application, rollback, regression, and registry components exist behind explicit approval/security/regression gates and are tested only against generic temporary workspaces. The default lifecycle never invokes them.

## Part 3 capabilities

- Generic Ollama runtime plugin plus runtime-plugin registry/extension contracts
- Durable content/deployment/composition identity reconciliation and alias-collision ledger
- Bounded generic GGUF v2/v3 header, metadata, and tensor-table inspection
- Unknown-architecture-safe metadata interpretation and architecture plugin extension point
- Generic tokenizer and static chat-template inspection
- Expanded safe behavioral probes, including bounded context and declared multimodal input
- Layered adapter catalog, configuration-first resolution, and untrusted generated proposals
- Production sandbox contracts with explicit requested/enforced controls
- Clearly labeled reference subprocess backend that is **not** a security boundary
- Resolver-gated, content-addressed artifact ingestion and typed probe-result binding
- Structured security assessment
- Versioned proposed-package envelope over the preserved Phase 1/2 package
- Immutable content-addressed package store
- Exact package/change/target/permission/policy/rollback approval binding
- Generic reversible application manager for explicitly supplied non-SAGE workspaces
- Fail-closed before/after regression framework
- Approval/regression/evidence-gated validated capability registry
- Separate untrusted hypothesis store
- Opt-in live read-only Ollama evidence collection command

## Non-negotiable boundaries

- No model-family branches in production source.
- Runtime tags and filenames are aliases, not durable identity.
- Missing evidence means `UNKNOWN`, never automatic `NOT_SUPPORTED`.
- API syntax/parameter acceptance is not behavioral capability validation.
- Generated adapter proposals remain `UNTRUSTED_GENERATED`.
- The reference subprocess backend refuses untrusted generated code and mandatory controls it cannot enforce.
- Sandbox files cannot become evidence until resolver and typed-ingestion checks pass.
- A submitted package is immutable; changes create a new digest and require new approval.
- Blocking security or mandatory regression failures fail closed.
- Only validated test-backed capabilities can enter the validated registry.
- No SAGE import, path, write, registration, or integration exists.

## Important files

Architecture and decisions:

- `docs/architecture-specification.md`
- `docs/component-contracts.md`
- `docs/security-and-approval.md`
- `docs/decisions/ADR-007-sandbox-truthfulness-and-artifact-gate.md`
- `docs/decisions/ADR-008-versioned-proposed-package-envelope.md`
- `docs/decisions/ADR-009-reference-approval-gated-application.md`

Inspection:

- `src/model_integration_engine/inspectors/gguf.py`
- `src/model_integration_engine/inspectors/tokenizer.py`
- `src/model_integration_engine/inspectors/template.py`

Sandbox and artifacts:

- `src/model_integration_engine/sandbox/contracts.py`
- `src/model_integration_engine/sandbox/reference.py`
- `src/model_integration_engine/sandbox/artifacts.py`
- `src/model_integration_engine/sandbox/probe_artifacts.py`

Lifecycle:

- `src/model_integration_engine/runtimes/`
- `src/model_integration_engine/identity/reconciliation.py`
- `src/model_integration_engine/adapters/engine.py`
- `src/model_integration_engine/security/assessment.py`
- `src/model_integration_engine/packaging/proposed.py`
- `src/model_integration_engine/approval/binding.py`
- `src/model_integration_engine/regression/framework.py`
- `src/model_integration_engine/application/changes.py`
- `src/model_integration_engine/registry/capability_registry.py`
- `src/model_integration_engine/application/lifecycle.py`

Schemas and samples:

- `schemas/integration-package.schema.json`
- `schemas/proposed-integration-package.schema.json`
- `schemas/capability-registry.schema.json`
- `reports/samples/part3-proposed-integration-package.json`
- `reports/samples/part3-capability-registry.example.json`
- `reports/samples/part3-evidence-chain.example.json`

## Test

```bash
python -m pytest -q
python -m compileall -q src tests
```

The normal suite is deterministic and offline. The live test remains opt-in.

## Live read-only validation hook

```bash
python -m model_integration_engine.live_validation \
  --endpoint http://host:11434 \
  --model <exact-runtime-reference> \
  --output live-evidence.json
```

This collects actual runtime/model-detail evidence only. It explicitly reports that behavioral probes are blocked until a production security sandbox is configured. It does not pull, create, copy, delete, integrate, approve, or register a model.

## Stop boundary

Part 3 ends after immutable package submission and creation of a pending human approval request. Do not proceed to application from the default workflow, and do not integrate with SAGE.
