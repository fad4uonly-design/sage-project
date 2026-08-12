# Security, Trust, Approval, and Reversibility

## 1. Threat model

MIE handles model artifacts, templates, runtime responses, generated code, and test outputs as untrusted. Relevant threats include:

- malicious or malformed binary metadata causing parser exploitation or resource exhaustion;
- path traversal, symlink escape, decompression/manifest bombs, or huge metadata fields;
- prompt/chat templates causing unsafe expansion or parser abuse;
- local model directories containing executable loaders, pickle payloads, shell hooks, or shared libraries;
- runtime endpoint spoofing, API-version drift, response smuggling, or over-broad network access;
- prompt injection in metadata/provider descriptions attempting to alter engine policy;
- generated adapters exfiltrating data or modifying the host/target;
- model output requesting consequential tool calls during evaluation;
- poisoned tests or evidence that falsely elevates a capability;
- tag mutation causing stale evidence to be attached to new bytes;
- approval replay against changed code, permissions, target state, or policy;
- registry corruption or unauthorized capability activation;
- leakage of credentials, host paths, prompts, outputs, or reasoning traces.

## 2. Trust matrix

| Input/component | Initial trust | Permitted use before validation |
|---|---|---|
| Core policy/schema | Reviewed trusted baseline | Orchestration and validation |
| Runtime metadata | Untrusted observation | Evidence only |
| GGUF/local metadata | Untrusted observation | Bounded parsing only |
| Chat template | Untrusted data | Bounded static parse/render in sandbox |
| Provider documentation | Untrusted external declaration | Hypothesis/provenance only |
| Model output | Untrusted | Test result input; never policy/instructions |
| Existing reviewed adapter | Trusted only for recorded version/digest | Sandbox tests and approved protocol access |
| Configured adapter | Review required | Sandbox only until validated |
| Generated code/tool/skill | Untrusted generated | Static analysis + sandbox only |
| Sandbox result | Attested observation | Evidence, subject to backend controls |
| Human approval | Trusted only if authenticated and scope matches | Authorizes exact future change scope |

## 3. Safe inspection requirements

- Parse binary lengths/counts before allocation and enforce configured maxima.
- Read the smallest necessary ranges; avoid loading weights for metadata inspection.
- Use parser processes/sandboxes for complex untrusted formats when available.
- Canonicalize paths and deny traversal/symlink escape.
- Never use model repository imports, pickle deserialization, `eval`, shell interpolation, or `trust_remote_code`.
- Preserve unknown metadata as data; do not interpret it as commands.
- Limit template parse/render time, memory, output length, recursion, and available functions/filters.
- Hash source bytes or manifests so every observation is tied to content.

## 4. Sandbox policy

### 4.1 Minimum controls for generated code

- disposable container or stronger isolation backend;
- non-root UID/GID;
- read-only root/candidate/test inputs;
- tmpfs or disposable scratch directory;
- no SAGE/target mounts;
- no Docker/control sockets, host PID namespace, or privileged capabilities;
- seccomp/capability restrictions where backend supports them;
- CPU/memory/process/file-size/disk/time/output limits;
- no network by default;
- explicit allowlist to a validation runtime endpoint only when required;
- empty environment plus scoped values; no inherited secrets;
- teardown and host-write verification.

A local subprocess is an execution harness, not a security sandbox. If the platform cannot provide mandatory controls, generated-code execution is blocked and the package records `SANDBOX_CONTROL_UNAVAILABLE`.

### 4.2 Runtime access

When the sandbox must reach a host-local runtime:

- allow only the exact approved endpoint;
- use read/inference methods required by the plan;
- deny model create/pull/push/delete/copy operations;
- use request budgets and timeouts;
- do not expose unrelated host services;
- record endpoint identity, runtime version, and actual route policy.

### 4.3 Tool-use tests

Tools are fake, deterministic, side-effect free, and scoped to the test harness. The model may propose a tool call; the sandbox harness decides whether and how to return a fixture. No shell, filesystem mutation, email, purchase, account, network search, or target operation is available.

## 5. Approval protocol

### 5.1 What approval covers

An approval event binds:

1. canonical integration package digest;
2. proposed-change-set digest;
3. target-profile/current-state digest;
4. permission-set digest;
5. policy version;
6. rollback plan digest;
7. conditions and expiry.

The reviewer sees a human-readable summary and the machine-readable package. Approval is explicit; silence, test success, or continued conversation is not approval.

### 5.2 Invalidation

Approval becomes invalid if any of the following changes:

- artifact/model/runtime/deployment digest or version;
- adapter source/configuration;
- proposed target changes;
- requested permissions;
- target profile/current-state snapshot;
- applicable security/evaluation policy;
- blocking risk or regression outcome;
- rollback plan.

A non-material report formatting change may be excluded only by a versioned canonicalization policy.

### 5.3 Decisions

- `APPROVE`: authorizes the exact scoped future operation.
- `REJECT`: closes that proposal; evidence remains.
- `REQUEST_CHANGES`: returns to planning and requires a new package/digest.
- `EXPIRE/REVOKE`: removes unused authorization or disables future continuation.

Models and generated components cannot be approval actors.

## 6. Future change application requirements

No applier exists in Phase 1. A future implementation must:

- run under separate, least-privilege credentials;
- verify approval scope immediately before writes;
- verify target preconditions/current-state digest;
- stage changes outside the active installation;
- run preflight regression and policy checks;
- create a version/snapshot and rollback checkpoint;
- apply atomically or transactionally where possible;
- emit an append-only change ledger;
- run post-application smoke/regression checks;
- automatically stop and propose/execute policy-approved rollback on failure;
- never rewrite engine architecture based on generated code without a separate reviewed engine release.

## 7. Reversibility checklist

Every proposed change must answer:

- What exact files/configuration/registry records would change?
- What are their before and after digests?
- Can the change be disabled without deleting evidence?
- What state is backed up and where is its digest?
- What command/API performs rollback, under what authority?
- Has rollback been tested in staging?
- What external side effects cannot be reversed?
- What health signal triggers rollback?

A proposal with irreversible or unknown consequences is blocked unless a human explicitly accepts the documented residual risk under a future policy.

## 8. Evidence and audit integrity

- Append-only transition, evidence, and approval records.
- Content-addressed artifacts and canonical package hashes.
- Collector, plugin, schema, policy, and test-suite versions in every record.
- Cryptographic signatures are recommended for production approval and registry releases.
- Redaction is explicit; dependent claims are invalidated if their required evidence is removed.
- Logs are supplementary. A critical decision must be represented structurally.

## 9. Data handling

- Never persist API keys, bearer tokens, cookies, or local credential files.
- Use credential references resolved only inside the authorized boundary.
- Default to output digests/assertion summaries instead of full prompts and responses.
- Treat model reasoning/thinking channels as potentially sensitive and unnecessary for most outcome validation.
- Store model and evaluation licenses/provenance.
- Network-derived enrichment is optional, cached with source URL/time/digest, and cannot masquerade as local test evidence.

## 10. Security acceptance gates

Before any generated candidate can reach `PROPOSED`:

- source/configuration manifest is complete;
- static policy checks pass or risks are explicitly blocking;
- mandatory sandbox controls are actually enforced;
- no unexpected host write/network attempt is observed;
- test tool set is non-consequential;
- output/log redaction policy is applied;
- permissions are least-privilege and included in approval scope;
- rollback/removal plan exists.
