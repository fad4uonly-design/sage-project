from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from model_integration_engine.application.probes import MinimalProbePlanner
from model_integration_engine.domain import SubjectKind, SubjectRef
from model_integration_engine.evidence import sha256_digest
from model_integration_engine.sandbox.artifacts import (
    ArtifactResolutionError,
    SecureArtifactResolver,
)
from model_integration_engine.sandbox.contracts import (
    ArtifactDeclaration,
    CodeTrust,
    CollectedArtifactCandidate,
    IsolationClass,
    NetworkMode,
    NetworkPolicy,
    ProcessLimits,
    SandboxControl,
    SandboxExecutionSpec,
    SandboxOutcome,
    SandboxPolicy,
)
from model_integration_engine.sandbox.probe_artifacts import ProbeArtifactIngestor
from model_integration_engine.sandbox.reference import ReferenceSubprocessSandbox

from tests.phase3_support import probe_artifact_document


def policy(*controls) -> SandboxPolicy:
    return SandboxPolicy(
        policy_id="test-policy",
        policy_version="0.3.0",
        required_controls=frozenset(controls),
        network=NetworkPolicy(NetworkMode.INHERIT),
        limits=ProcessLimits(timeout_seconds=5, cpu_seconds=2),
        filesystem_isolation_required=False,
        non_root_required=False,
    )


def test_reference_backend_truthfully_blocks_untrusted_or_missing_controls(tmp_path) -> None:
    backend = ReferenceSubprocessSandbox(
        tmp_path / "runs", tmp_path / "collections"
    )
    spec = SandboxExecutionSpec(
        run_id="untrusted",
        argv=(sys.executable, "-c", "print('should not run')"),
        environment={},
        mounts=(),
        output_directory="outputs",
        artifacts=(),
        policy=policy(
            SandboxControl.CONTROLLED_EXECUTION,
            SandboxControl.FILESYSTEM_ISOLATION,
            SandboxControl.NETWORK_POLICY,
        ),
        code_trust=CodeTrust.UNTRUSTED_GENERATED,
    )
    result = backend.execute(spec)
    assert result.outcome is SandboxOutcome.BLOCKED
    assert result.isolation_class is IsolationClass.REFERENCE_NOT_SECURITY_BOUNDARY
    assert result.security_boundary_claimed is False
    assert result.problem_code == "REFERENCE_BACKEND_UNSAFE_FOR_UNTRUSTED"


def test_reference_backend_captures_artifacts_and_cleans_execution(tmp_path) -> None:
    backend = ReferenceSubprocessSandbox(
        tmp_path / "runs", tmp_path / "collections"
    )
    declaration = ArtifactDeclaration(
        artifact_id="result",
        relative_path="result.json",
        media_type="application/json",
    )
    script = (
        "from pathlib import Path; "
        "Path('outputs').mkdir(exist_ok=True); "
        "Path('outputs/result.json').write_text('{\"ok\": true}')"
    )
    required = {
        SandboxControl.CONTROLLED_EXECUTION,
        SandboxControl.PROCESS_LIMITS,
        SandboxControl.ARTIFACT_ALLOWLIST,
        SandboxControl.ARTIFACT_DIGESTING,
        SandboxControl.RESULT_CAPTURE,
        SandboxControl.FAILURE_ISOLATION,
        SandboxControl.CLEAN_ENVIRONMENT,
        SandboxControl.CLEANUP,
        SandboxControl.TIMEOUT,
    }
    result = backend.execute(
        SandboxExecutionSpec(
            run_id="trusted-harness",
            argv=(sys.executable, "-c", script),
            environment={},
            mounts=(),
            output_directory="outputs",
            artifacts=(declaration,),
            policy=policy(*required),
            code_trust=CodeTrust.TRUSTED_ENGINE_HARNESS,
        )
    )
    assert result.outcome is SandboxOutcome.PASS
    assert result.cleanup_complete is True
    assert result.security_boundary_claimed is False
    assert len(result.artifacts) == 1
    assert not any((tmp_path / "runs").iterdir())

    resolver = SecureArtifactResolver(tmp_path / "artifact-store")
    resolution = resolver.resolve(
        collection_root=Path(result.artifacts[0].collection_root),
        declarations=(declaration,),
        candidates=result.artifacts,
        run_id=result.run_id,
    )
    assert json.loads(resolver.read_verified(resolution.artifacts[0])) == {"ok": True}
    assert resolution.manifest_digest.startswith("sha256:")


def test_artifact_tampering_and_injection_are_rejected(tmp_path) -> None:
    collection = tmp_path / "collection"
    collection.mkdir()
    path = collection / "result.json"
    path.write_text('{"ok": true}', encoding="utf-8")
    digest = sha256_digest(path.read_bytes())
    declaration = ArtifactDeclaration("result", "result.json", "application/json")
    candidate = CollectedArtifactCandidate(
        artifact_id="result",
        relative_path="result.json",
        media_type="application/json",
        size_bytes=path.stat().st_size,
        reported_digest=digest,
        collection_root=str(collection),
        run_id="run",
    )
    resolver = SecureArtifactResolver(tmp_path / "store")
    path.write_text('{"ok": false}', encoding="utf-8")
    with pytest.raises(ArtifactResolutionError) as error:
        resolver.resolve(
            collection_root=collection,
            declarations=(declaration,),
            candidates=(candidate,),
            run_id="run",
        )
    assert error.value.code == "ARTIFACT_DIGEST_MISMATCH"

    path.write_text('{"ok": true}', encoding="utf-8")
    (collection / "injected.py").write_text("malicious", encoding="utf-8")
    with pytest.raises(ArtifactResolutionError) as error:
        resolver.resolve(
            collection_root=collection,
            declarations=(declaration,),
            candidates=(candidate,),
            run_id="run",
        )
    assert error.value.code == "UNEXPECTED_ARTIFACT"


def test_resolved_store_tampering_is_detected_on_read(tmp_path) -> None:
    collection = tmp_path / "collection"
    collection.mkdir()
    source = collection / "evidence.json"
    source.write_text('{"evidence": []}', encoding="utf-8")
    digest = sha256_digest(source.read_bytes())
    declaration = ArtifactDeclaration("ev", "evidence.json", "application/json")
    candidate = CollectedArtifactCandidate(
        "ev", "evidence.json", "application/json", source.stat().st_size,
        digest, str(collection), "run"
    )
    resolver = SecureArtifactResolver(tmp_path / "store")
    resolved = resolver.resolve(
        collection_root=collection,
        declarations=(declaration,),
        candidates=(candidate,),
        run_id="run",
    ).artifacts[0]
    stored = Path(resolved.store_path)
    stored.chmod(0o600)
    stored.write_text("tampered", encoding="utf-8")
    with pytest.raises(ArtifactResolutionError) as error:
        resolver.read_verified(resolved)
    assert error.value.code == "RESOLVED_ARTIFACT_TAMPERED"


def test_probe_artifact_ingestion_is_bound_to_plan_and_subject(tmp_path) -> None:
    deployment = SubjectRef(
        SubjectKind.DEPLOYMENT, "deployment:test", digest=sha256_digest("deployment")
    )
    runtime = SubjectRef(
        SubjectKind.RUNTIME, "runtime:test", digest=sha256_digest("runtime")
    )
    plan = MinimalProbePlanner().plan(
        deployment=deployment,
        runtime=runtime,
        adapter_id="adapter:test",
        configuration_digest=sha256_digest("config"),
        environment_id="env:test",
        hypotheses=(),
    )
    collection = tmp_path / "collection"
    collection.mkdir()
    result_path = collection / "probe-results.json"
    document = probe_artifact_document(plan, "sandbox-run")
    result_path.write_text(json.dumps(document), encoding="utf-8")
    declaration = ArtifactDeclaration(
        "probe-results",
        "probe-results.json",
        "application/vnd.mie.probe-results+json",
    )
    candidate = CollectedArtifactCandidate(
        "probe-results", "probe-results.json", declaration.media_type,
        result_path.stat().st_size, sha256_digest(result_path.read_bytes()),
        str(collection), "sandbox-run"
    )
    resolver = SecureArtifactResolver(tmp_path / "store")
    artifact = resolver.resolve(
        collection_root=collection,
        declarations=(declaration,),
        candidates=(candidate,),
        run_id="sandbox-run",
    ).artifacts[0]
    typed = ProbeArtifactIngestor().ingest(
        artifact=artifact,
        resolver=resolver,
        expected_plan=plan,
        expected_run_id="sandbox-run",
    )
    assert {item.probe_id for item in typed} == {item.probe_id for item in plan.cases}

    document["results"][0]["subject"]["subject_id"] = "deployment:injected"
    result_path.write_text(json.dumps(document), encoding="utf-8")
    tampered_candidate = CollectedArtifactCandidate(
        "probe-results", "probe-results.json", declaration.media_type,
        result_path.stat().st_size, sha256_digest(result_path.read_bytes()),
        str(collection), "sandbox-run"
    )
    tampered_artifact = SecureArtifactResolver(tmp_path / "store2").resolve(
        collection_root=collection,
        declarations=(declaration,),
        candidates=(tampered_candidate,),
        run_id="sandbox-run",
    ).artifacts[0]
    with pytest.raises(ArtifactResolutionError) as error:
        ProbeArtifactIngestor().ingest(
            artifact=tampered_artifact,
            resolver=SecureArtifactResolver(tmp_path / "store2"),
            expected_plan=plan,
            expected_run_id="sandbox-run",
        )
    assert error.value.code == "PROBE_ARTIFACT_SUBJECT_MISMATCH"
