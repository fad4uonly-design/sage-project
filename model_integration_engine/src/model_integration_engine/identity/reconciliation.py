"""Content/deployment/composition-scoped model identity reconciliation."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from ..domain import (
    EvidenceKind,
    EvidenceLevel,
    EvidenceOutcome,
    EvidenceRecord,
    JSONValue,
    SubjectKind,
    SubjectRef,
)
from ..evidence import EvidenceFactory, deterministic_id, sha256_digest, utc_now


@dataclass(frozen=True, slots=True)
class IdentityInputs:
    runtime: SubjectRef
    runtime_kind: str
    runtime_model_reference: str
    artifact: SubjectRef | None
    deployment: SubjectRef
    adapter: SubjectRef
    configuration_digest: str
    environment_digest: str
    model_metadata: Mapping[str, JSONValue]
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ReconciledIdentity:
    logical_model: SubjectRef
    artifact: SubjectRef | None
    deployment: SubjectRef
    composition: SubjectRef
    identity_status: str
    alias_collision: bool
    identity_material_digest: str
    components: Mapping[str, JSONValue]
    evidence: tuple[EvidenceRecord, ...]


class IdentityLedger:
    """Atomic alias-to-content observation ledger; never merges differing bytes."""

    def __init__(self, path: Path) -> None:
        self.path = path.resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def observe(self, runtime_id: str, alias: str, content_digest: str | None) -> bool:
        state = self._load()
        key = sha256_digest({"runtime_id": runtime_id, "alias": alias})
        values = set(state.get(key, []))
        if content_digest is not None:
            values.add(content_digest)
        state[key] = sorted(values)
        self._write(state)
        return len(values) > 1

    def _load(self) -> dict[str, list[str]]:
        if not self.path.exists():
            return {}
        value = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("identity ledger is malformed")
        return {
            str(key): [str(item) for item in values]
            for key, values in value.items()
            if isinstance(values, list)
        }

    def _write(self, state: dict[str, list[str]]) -> None:
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(state, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, self.path)


@dataclass(slots=True)
class ModelIdentityReconciler:
    ledger: IdentityLedger | None = None
    clock: callable = utc_now
    policy_version: str = "identity-policy-0.3.0"

    def reconcile(self, inputs: IdentityInputs) -> ReconciledIdentity:
        content_digest = inputs.artifact.digest if inputs.artifact else None
        metadata_identity = {
            key: value
            for key, value in sorted(inputs.model_metadata.items())
            if key
            in {
                "general.name",
                "general.basename",
                "general.version",
                "general.uuid",
                "general.repo_url",
                "general.source.repo_url",
                "general.finetune",
                "general.architecture",
            }
        }
        model_material = {
            "artifact_digest": content_digest,
            "metadata_identity": metadata_identity,
        }
        if content_digest is None:
            model_material.update(
                {
                    "runtime_id": inputs.runtime.subject_id,
                    "deployment_id": inputs.deployment.subject_id,
                    "runtime_reference": inputs.runtime_model_reference,
                }
            )
        identity_material_digest = sha256_digest(model_material)
        logical_model = SubjectRef(
            SubjectKind.MODEL,
            deterministic_id("model:reconciled", identity_material_digest),
            version=str(metadata_identity.get("general.version"))
            if metadata_identity.get("general.version") is not None
            else None,
            digest=content_digest,
        )
        deployment_digest = sha256_digest(
            {
                "runtime": inputs.runtime.digest,
                "runtime_kind": inputs.runtime_kind,
                "reference": inputs.runtime_model_reference,
                "artifact": content_digest,
                "deployment_observation": inputs.deployment.digest,
            }
        )
        deployment = SubjectRef(
            SubjectKind.DEPLOYMENT,
            deterministic_id("deployment:reconciled", deployment_digest),
            digest=deployment_digest,
        )
        composition_digest = sha256_digest(
            {
                "model": logical_model.subject_id,
                "artifact": content_digest,
                "runtime": inputs.runtime.digest,
                "deployment": deployment.digest,
                "adapter": inputs.adapter.digest,
                "configuration": inputs.configuration_digest,
                "environment": inputs.environment_digest,
            }
        )
        composition = SubjectRef(
            SubjectKind.INTEGRATION,
            deterministic_id("composition", composition_digest),
            digest=composition_digest,
        )
        collision = (
            self.ledger.observe(
                inputs.runtime.subject_id,
                inputs.runtime_model_reference,
                content_digest,
            )
            if self.ledger
            else False
        )
        if collision:
            status = "ALIAS_COLLISION_DETECTED"
        elif content_digest:
            status = "CONTENT_RECONCILED"
        else:
            status = "PROVISIONAL_DEPLOYMENT_SCOPED"

        components = {
            "runtime_id": inputs.runtime.subject_id,
            "runtime_digest": inputs.runtime.digest,
            "runtime_kind": inputs.runtime_kind,
            "runtime_model_reference": inputs.runtime_model_reference,
            "artifact_digest": content_digest,
            "deployment_digest": deployment.digest,
            "adapter_id": inputs.adapter.subject_id,
            "adapter_digest": inputs.adapter.digest,
            "configuration_digest": inputs.configuration_digest,
            "environment_digest": inputs.environment_digest,
            "metadata_identity": metadata_identity,
        }
        factory = EvidenceFactory(
            "mie.identity.reconciler", "0.3.0", self.clock
        )
        if inputs.evidence_ids:
            evidence = factory.create(
                kind=EvidenceKind.DERIVATION,
                level=EvidenceLevel.INFERRED,
                subject=composition,
                observation_key="identity.reconciliation",
                observed_value={
                    "status": status,
                    "identity_material_digest": identity_material_digest,
                    "components": components,
                    "alias_collision": collision,
                },
                source_uri=f"urn:mie:identity-policy:{self.policy_version}",
                source_digest=sha256_digest({"policy": self.policy_version}),
                locator="reconcile",
                outcome=EvidenceOutcome.NOT_APPLICABLE,
                derived_from=inputs.evidence_ids,
            )
        else:
            evidence = factory.create(
                kind=EvidenceKind.STATIC_ANALYSIS,
                level=EvidenceLevel.UNKNOWN,
                subject=composition,
                observation_key="identity.reconciliation",
                observed_value={
                    "status": status,
                    "identity_material_digest": identity_material_digest,
                    "components": components,
                    "alias_collision": collision,
                },
                source_uri=f"urn:mie:identity-policy:{self.policy_version}",
                source_digest=sha256_digest({"policy": self.policy_version}),
                locator="reconcile",
                outcome=EvidenceOutcome.INCONCLUSIVE,
            )
        return ReconciledIdentity(
            logical_model=logical_model,
            artifact=inputs.artifact,
            deployment=deployment,
            composition=composition,
            identity_status=status,
            alias_collision=collision,
            identity_material_digest=identity_material_digest,
            components=components,
            evidence=(evidence,),
        )
