"""Read-only, model-agnostic capability delta against a registry snapshot."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ..domain import CapabilityClaim, SupportState, ValidationState
from ..evidence import sha256_digest


@dataclass(frozen=True, slots=True)
class CapabilityDeltaResult:
    status: str
    baseline_snapshot_digest: str | None
    added: tuple[str, ...]
    improved: tuple[str, ...]
    redundant: tuple[str, ...]
    regressed: tuple[str, ...]
    unknown: tuple[str, ...]
    policy_version: str
    reasons: tuple[str, ...]

    def package_document(self) -> dict[str, Any]:
        """Return the strict integration-package schema representation."""

        return {
            "baseline_snapshot_digest": self.baseline_snapshot_digest,
            "added": list(self.added),
            "improved": list(self.improved),
            "redundant": list(self.redundant),
            "regressed": list(self.regressed),
            "unknown": list(self.unknown),
            "policy_version": self.policy_version,
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            **self.package_document(),
            "reasons": list(self.reasons),
            "read_only": True,
        }


@dataclass(slots=True)
class GenericCapabilityDeltaComparator:
    """Compare validated candidate claims without mutating the registry."""

    policy_version: str = "delta-policy-0.3.0"

    def compare(
        self,
        claims: tuple[CapabilityClaim, ...],
        registry_snapshot: Mapping[str, Any] | None,
    ) -> CapabilityDeltaResult:
        ordered = tuple(sorted(claims, key=lambda item: item.claim_id))
        if registry_snapshot is None:
            return CapabilityDeltaResult(
                status="UNKNOWN_NO_REGISTRY_SNAPSHOT",
                baseline_snapshot_digest=None,
                added=(),
                improved=(),
                redundant=(),
                regressed=(),
                unknown=tuple(item.claim_id for item in ordered),
                policy_version=self.policy_version,
                reasons=(
                    "No read-only registry snapshot was supplied; capability delta is unknown.",
                ),
            )

        baseline_digest = sha256_digest(dict(registry_snapshot))
        entries = registry_snapshot.get("entries")
        if not isinstance(entries, list):
            raise ValueError("registry snapshot requires an entries array")
        baseline: dict[str, list[Mapping[str, Any]]] = {}
        for entry in entries:
            if not isinstance(entry, Mapping) or entry.get("status") != "ACTIVE":
                continue
            capabilities = entry.get("capabilities")
            if not isinstance(capabilities, list):
                continue
            for capability in capabilities:
                if not isinstance(capability, Mapping):
                    continue
                key = capability.get("capability_key")
                if isinstance(key, str) and key:
                    baseline.setdefault(key, []).append(capability)

        added: list[str] = []
        improved: list[str] = []
        redundant: list[str] = []
        unknown: list[str] = []
        reasons: list[str] = []
        for claim in ordered:
            eligible = (
                claim.validation is ValidationState.VALIDATED
                and claim.support in {SupportState.SUPPORTED, SupportState.PARTIAL}
            )
            if not eligible:
                unknown.append(claim.claim_id)
                reasons.append(
                    f"{claim.capability_key}: candidate is not behaviorally validated."
                )
                continue
            existing = baseline.get(claim.capability_key, [])
            validated_existing = [
                item
                for item in existing
                if item.get("validation") == "VALIDATED"
                and item.get("support") in {"SUPPORTED", "PARTIAL"}
            ]
            if not validated_existing:
                added.append(claim.claim_id)
                reasons.append(
                    f"{claim.capability_key}: no active validated registry capability exists."
                )
                continue

            candidate_score = _score(claim.parameters)
            baseline_scores = [
                score
                for item in validated_existing
                if (score := _score(item.get("parameters"))) is not None
            ]
            if candidate_score is not None and baseline_scores:
                if candidate_score > max(baseline_scores):
                    improved.append(claim.claim_id)
                    reasons.append(
                        f"{claim.capability_key}: comparable candidate score is higher."
                    )
                else:
                    redundant.append(claim.claim_id)
                    reasons.append(
                        f"{claim.capability_key}: comparable active capability is retained."
                    )
            else:
                redundant.append(claim.claim_id)
                reasons.append(
                    f"{claim.capability_key}: active validated capability already exists; no comparable improvement metric was supplied."
                )

        return CapabilityDeltaResult(
            status="COMPARED_READ_ONLY",
            baseline_snapshot_digest=baseline_digest,
            added=tuple(added),
            improved=tuple(improved),
            redundant=tuple(redundant),
            regressed=(),
            unknown=tuple(unknown),
            policy_version=self.policy_version,
            reasons=tuple(reasons),
        )


def _score(parameters: object) -> float | None:
    if not isinstance(parameters, Mapping):
        return None
    value = parameters.get("score")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None
