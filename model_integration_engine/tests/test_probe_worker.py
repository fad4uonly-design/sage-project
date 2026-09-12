from datetime import UTC, datetime

import pytest
from model_integration_engine.application.probes import (
    ProbeCase,
    ProbeKind,
    ProbePlan,
)
from model_integration_engine.contracts import ResourceLimits
from model_integration_engine.domain import SubjectKind, SubjectRef
from model_integration_engine.sandbox.probe_worker_contract import (
    ProbeWorkerContextSpec,
    ProbeWorkerSpec,
)


def _subjects():
    runtime = SubjectRef(
        SubjectKind.RUNTIME,
        "runtime:test",
        "1.0",
        "sha256:" + "1" * 64,
    )
    deployment = SubjectRef(
        SubjectKind.DEPLOYMENT,
        "deployment:test",
        "1.0",
        "sha256:" + "2" * 64,
    )
    return runtime, deployment


def _plan():
    runtime, deployment = _subjects()
    case = ProbeCase(
        "probe:test",
        ProbeKind.BASIC_GENERATION,
        "generation.text",
        deployment,
        "sha256:" + "4" * 64,
    )
    return ProbePlan(
        "plan:test",
        "mie.safe-vertical-slice",
        "0.2.0",
        deployment,
        runtime,
        "mie.adapter.ollama-chat",
        "sha256:" + "3" * 64,
        "env:test",
        (case,),
        (
            "read_only_inputs",
            "ephemeral_scratch",
            "network_allowlist",
            "no_target_mount",
            "resource_limits",
        ),
    )


def _context():
    return ProbeWorkerContextSpec(
        "probe-run:test",
        "corr:test",
        datetime.now(UTC),
        "mie.probe",
        "1",
        "workspace:test",
        ("network:http://host.docker.internal:11434",),
        ResourceLimits(timeout_seconds=30),
    )


def _spec():
    plan = _plan()
    runtime, deployment = _subjects()
    config = {
        "runtime": runtime.subject_id,
        "deployment": deployment.subject_id,
        "model_reference": "test-model",
        "configuration_digest": plan.configuration_digest,
        "runtime_owns_template": True,
    }
    return ProbeWorkerSpec.create(
        run_id="probe-run:test",
        runtime_locator="http://host.docker.internal:11434",
        adapter_id=plan.adapter_id,
        adapter_configuration=config,
        plan=plan,
        context=_context(),
        output_artifact_path="/mie/output/probe-results.json",
    )


def test_worker_spec_round_trip_preserves_digest():
    spec = _spec()

    restored = ProbeWorkerSpec.from_document(spec.to_document())

    assert restored == spec
    assert restored.digest == spec.digest


def test_worker_spec_binds_context_run_id():
    plan = _plan()
    runtime, _ = _subjects()
    config = {
        "runtime": runtime.subject_id,
        "deployment": plan.deployment.subject_id,
        "model_reference": "test-model",
        "configuration_digest": plan.configuration_digest,
    }
    context = ProbeWorkerContextSpec(
        "different-run",
        "corr:test",
        datetime.now(UTC),
        "mie.probe",
        "1",
        "workspace:test",
        (),
        ResourceLimits(timeout_seconds=30),
    )

    with pytest.raises(ValueError, match="run_id"):
        ProbeWorkerSpec.create(
            run_id="probe-run:test",
            runtime_locator="http://host.docker.internal:11434",
            adapter_id=plan.adapter_id,
            adapter_configuration=config,
            plan=plan,
            context=context,
            output_artifact_path="/mie/output/probe-results.json",
        )


def test_worker_spec_binds_configuration_digest():
    plan = _plan()
    runtime, _ = _subjects()
    config = {
        "runtime": runtime.subject_id,
        "deployment": plan.deployment.subject_id,
        "model_reference": "test-model",
        "configuration_digest": "sha256:" + "9" * 64,
    }

    with pytest.raises(ValueError, match="configuration digest"):
        ProbeWorkerSpec.create(
            run_id="probe-run:test",
            runtime_locator="http://host.docker.internal:11434",
            adapter_id=plan.adapter_id,
            adapter_configuration=config,
            plan=plan,
            context=_context(),
            output_artifact_path="/mie/output/probe-results.json",
        )


def test_worker_spec_rejects_unknown_schema():
    document = _spec().to_document()
    document["schema_version"] = "999.0.0"

    with pytest.raises(ValueError, match="schema version"):
        ProbeWorkerSpec.from_document(document)
