# Windows Real-Deployment Acceptance Procedure

This procedure must be run **on the Windows machine that hosts Ollama**. In this command, `http://localhost:11434` must resolve to that Windows machine's Ollama service. Do not run it in Arena and do not replace the endpoint with Arena's localhost.

The generic runner does not pull, create, copy, delete, register, approve, or apply a model. Behavioral probes remain blocked until a production-qualified sandbox worker is configured.

## 1. Open PowerShell in the recovered project

```powershell
Set-Location C:\path\to\model-integration-engine
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e .
```

Confirm that the service and exact runtime reference are locally visible:

```powershell
Invoke-RestMethod -Method Get -Uri http://localhost:11434/api/version
Invoke-RestMethod -Method Get -Uri http://localhost:11434/api/tags
ollama list
```

These diagnostic commands do not replace MIE evidence collection; the runner will repeat the read-only API calls and hash its own responses.

## 2. Create the user-evidence input

The following records the independently supplied observations as `USER_INPUT`. It does not make any record `VALIDATED_BY_TEST`.

```powershell
New-Item -ItemType Directory -Force .\acceptance-input | Out-Null
@'
{
  "schema_version": "0.1.0",
  "source_id": "windows-operator-independent-checks",
  "observations": [
    {
      "subject_kind": "RUNTIME",
      "observation_key": "user.runtime.endpoint",
      "value": "http://localhost:11434",
      "level": "DETECTED_FROM_RUNTIME"
    },
    {
      "subject_kind": "DEPLOYMENT",
      "observation_key": "user.runtime.tags_http_status",
      "value": 200,
      "level": "DETECTED_FROM_RUNTIME"
    },
    {
      "subject_kind": "DEPLOYMENT",
      "observation_key": "user.runtime.model_reference_present",
      "value": "qwen3:4b",
      "level": "DETECTED_FROM_RUNTIME"
    },
    {
      "subject_kind": "DEPLOYMENT",
      "observation_key": "user.runtime.short_model_id",
      "value": "359d7dd4bcda",
      "level": "DETECTED_FROM_RUNTIME"
    },
    {
      "subject_kind": "DEPLOYMENT",
      "observation_key": "user.manual_model_execution",
      "value": {
        "command_succeeded": true,
        "response_topic": "agricultural reasoning",
        "response_bytes_or_digest_supplied": false
      },
      "level": "UNKNOWN"
    },
    {
      "subject_kind": "ARTIFACT",
      "observation_key": "user.gguf.metadata",
      "value": {
        "general.parameter_count": 4022468096,
        "general.size_label": "4B",
        "general.file_type": 15,
        "general.quantization_version": 2,
        "qwen3.block_count": 36,
        "qwen3.context_length": 262144,
        "qwen3.embedding_length": 2560,
        "qwen3.feed_forward_length": 9728,
        "qwen3.attention.head_count": 32,
        "qwen3.attention.head_count_kv": 8,
        "qwen3.attention.key_length": 128,
        "qwen3.attention.value_length": 128
      },
      "level": "DETECTED_FROM_METADATA"
    }
  ]
}
'@ | .\.venv\Scripts\python.exe -c "import pathlib,sys; pathlib.Path(r'acceptance-input\user-evidence.json').write_text(sys.stdin.read(), encoding='utf-8')"
```

The architecture-specific metadata keys above are input data only. They do not create production dispatch or a model-specific adapter.

## 3. Run metadata/deployment acceptance

```powershell
.\.venv\Scripts\python.exe -m model_integration_engine.acceptance `
  --endpoint http://localhost:11434 `
  --model qwen3:4b `
  --user-evidence .\acceptance-input\user-evidence.json `
  --output-dir .\reports\acceptance
```

Expected command state when discovery and `/api/show` succeed:

```text
state=DRAFT_PENDING_APPROVAL
approval_requested=false
```

## 4. Optional direct GGUF verification

Use this form only when the exact GGUF file is safely readable. Calculate its complete SHA-256 first; the 12-character Ollama model ID is not an artifact digest.

```powershell
$Artifact = 'C:\path\to\actual-model.gguf'
$Hash = (Get-FileHash -Algorithm SHA256 $Artifact).Hash.ToLowerInvariant()
$Digest = "sha256:$Hash"

.\.venv\Scripts\python.exe -m model_integration_engine.acceptance `
  --endpoint http://localhost:11434 `
  --model qwen3:4b `
  --artifact-path $Artifact `
  --artifact-digest $Digest `
  --user-evidence .\acceptance-input\user-evidence.json `
  --output-dir .\reports\acceptance
```

MIE hashes the file independently and fails on a digest mismatch. Runtime model/manifest digest and direct GGUF digest remain separate unless their relationship is proven.

## 5. Optional read-only registry comparison

If an actual registry snapshot exists, add:

```powershell
  --registry-snapshot C:\path\to\capability-registry.snapshot.json
```

The file is schema-validated and read only. The runner never invokes registry registration.

## 6. Verify the generated output manifest

```powershell
.\.venv\Scripts\python.exe -c "import hashlib,pathlib,sys; root=pathlib.Path(r'reports\acceptance'); bad=[]; lines=(root/'artifact-manifest.sha256').read_text(encoding='utf-8').splitlines(); [(bad.append(rel) if hashlib.sha256((root/rel.removeprefix('./')).read_bytes()).hexdigest()!=digest else None) for digest,rel in (line.split('  ',1) for line in lines if line)]; print('artifact manifest: PASS' if not bad else 'artifact manifest: FAIL '+str(bad)); sys.exit(bool(bad))"
```

## Expected output

```text
reports/acceptance/
├── acceptance-report.md
├── artifact-evidence.json
├── artifact-manifest.sha256
├── behavioral-probe-evidence.json
├── capability-assessment.json
├── capability-delta.json
├── compatibility-assessment.json
├── identity-ledger.json
├── identity-reconciliation.json
├── immutable-packages/
├── live-runtime-evidence.json
├── real-draft-integration-package.json
├── run-status.json
└── user-supplied-evidence.json
```

The package must remain `DRAFT_PENDING_APPROVAL`, its embedded approval state must remain `NOT_REQUESTED`, and `run-status.json` must report `approval_request_created: false`.
