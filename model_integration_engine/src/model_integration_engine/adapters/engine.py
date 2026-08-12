"""Generic layered adapter catalog, resolution, and generated-proposal gate."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Mapping

from ..domain import JSONValue, TrustState
from ..evidence import deterministic_id, sha256_digest
from ..sandbox.contracts import IsolationClass, SandboxExecutionResultV3, SandboxOutcome


class AdapterLayer(StrEnum):
    TRANSPORT = "TRANSPORT"
    RUNTIME_PROTOCOL = "RUNTIME_PROTOCOL"
    DEPLOYMENT_PROFILE = "DEPLOYMENT_PROFILE"
    OUTPUT_NORMALIZER = "OUTPUT_NORMALIZER"


class AdapterResolutionDisposition(StrEnum):
    REUSE = "REUSE"
    CONFIGURE = "CONFIGURE"
    GENERATE_PROPOSAL = "GENERATE_PROPOSAL"
    UNRESOLVED = "UNRESOLVED"


@dataclass(frozen=True, slots=True)
class AdapterSpec:
    adapter_id: str
    version: str
    runtime_kind: str
    contract_version: str
    operations: frozenset[str]
    layers: tuple[AdapterLayer, ...]
    artifact_digest: str
    reviewed: bool
    configurable: bool
    required_permissions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AdapterRequirement:
    runtime_kind: str
    contract_version: str
    operations: frozenset[str]
    deployment_id: str
    runtime_endpoint: str
    configuration: Mapping[str, JSONValue]
    allowed_permissions: frozenset[str]


@dataclass(frozen=True, slots=True)
class GeneratedAdapterProposal:
    proposal_id: str
    manifest: Mapping[str, JSONValue]
    artifact_digest: str
    trust_state: TrustState
    required_sandbox_controls: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AdapterResolution:
    disposition: AdapterResolutionDisposition
    adapter: AdapterSpec | None
    configuration_digest: str | None
    generated_proposal: GeneratedAdapterProposal | None
    considered: tuple[str, ...]
    reasons: tuple[str, ...]
    accepted: bool


@dataclass(slots=True)
class AdapterCatalog:
    _items: dict[str, AdapterSpec] = field(default_factory=dict)

    def register(self, spec: AdapterSpec) -> None:
        if spec.adapter_id in self._items:
            raise ValueError(f"duplicate adapter ID: {spec.adapter_id}")
        self._items[spec.adapter_id] = spec

    def candidates(self, requirement: AdapterRequirement) -> tuple[AdapterSpec, ...]:
        return tuple(
            sorted(
                (
                    item
                    for item in self._items.values()
                    if item.runtime_kind == requirement.runtime_kind
                    and item.contract_version == requirement.contract_version
                    and requirement.operations <= item.operations
                ),
                key=lambda item: (not item.reviewed, item.adapter_id, item.version),
            )
        )


@dataclass(slots=True)
class GenericAdapterEngine:
    catalog: AdapterCatalog

    def resolve(
        self,
        requirement: AdapterRequirement,
        *,
        permit_generated_proposal: bool = True,
    ) -> AdapterResolution:
        candidates = self.catalog.candidates(requirement)
        considered = tuple(item.adapter_id for item in candidates)
        for candidate in candidates:
            disallowed = set(candidate.required_permissions) - set(
                requirement.allowed_permissions
            )
            if disallowed:
                continue
            if candidate.configurable:
                configuration_digest = sha256_digest(
                    {
                        "adapter": candidate.artifact_digest,
                        "deployment": requirement.deployment_id,
                        "endpoint": requirement.runtime_endpoint,
                        "configuration": dict(requirement.configuration),
                    }
                )
                return AdapterResolution(
                    disposition=AdapterResolutionDisposition.CONFIGURE,
                    adapter=candidate,
                    configuration_digest=configuration_digest,
                    generated_proposal=None,
                    considered=considered,
                    reasons=("Existing compatible layered adapter can be configured.",),
                    accepted=candidate.reviewed,
                )
            return AdapterResolution(
                disposition=AdapterResolutionDisposition.REUSE,
                adapter=candidate,
                configuration_digest=None,
                generated_proposal=None,
                considered=considered,
                reasons=("Existing adapter satisfies the exact contract.",),
                accepted=candidate.reviewed,
            )

        if not permit_generated_proposal:
            return AdapterResolution(
                disposition=AdapterResolutionDisposition.UNRESOLVED,
                adapter=None,
                configuration_digest=None,
                generated_proposal=None,
                considered=considered,
                reasons=("No compatible allowed adapter exists; generation is disabled.",),
                accepted=False,
            )
        manifest = {
            "schema_version": "0.3.0",
            "runtime_kind": requirement.runtime_kind,
            "contract_version": requirement.contract_version,
            "required_operations": sorted(requirement.operations),
            "layers": [item.value for item in AdapterLayer],
            "deployment_binding": requirement.deployment_id,
            "status": "UNTRUSTED_GENERATED_PROPOSAL",
            "executable": False,
        }
        digest = sha256_digest(manifest)
        proposal = GeneratedAdapterProposal(
            proposal_id=deterministic_id("adapter-proposal", digest),
            manifest=manifest,
            artifact_digest=digest,
            trust_state=TrustState.UNTRUSTED_GENERATED,
            required_sandbox_controls=(
                "filesystem_isolation",
                "network_policy",
                "permission_boundary",
                "process_limits",
                "artifact_allowlist",
            ),
        )
        return AdapterResolution(
            disposition=AdapterResolutionDisposition.GENERATE_PROPOSAL,
            adapter=None,
            configuration_digest=None,
            generated_proposal=proposal,
            considered=considered,
            reasons=(
                "No existing adapter satisfied the requirement; generated artifact is a proposal only.",
            ),
            accepted=False,
        )

    def validate_generated_proposal(
        self,
        proposal: GeneratedAdapterProposal,
        sandbox_result: SandboxExecutionResultV3,
        resolved_artifact_digest: str,
    ) -> bool:
        if proposal.trust_state is not TrustState.UNTRUSTED_GENERATED:
            return False
        if sandbox_result.isolation_class is not IsolationClass.PRODUCTION_SECURITY_BOUNDARY:
            return False
        if not sandbox_result.security_boundary_claimed:
            return False
        if sandbox_result.outcome is not SandboxOutcome.PASS:
            return False
        if sandbox_result.missing_controls or not sandbox_result.cleanup_complete:
            return False
        return resolved_artifact_digest == proposal.artifact_digest


def generic_ollama_adapter_spec() -> AdapterSpec:
    return AdapterSpec(
        adapter_id="mie.adapter.ollama-chat",
        version="0.3.0",
        runtime_kind="ollama",
        contract_version="normalized-inference-0.1.0",
        operations=frozenset({"chat", "stream", "structured_output", "tools", "multimodal"}),
        layers=(
            AdapterLayer.TRANSPORT,
            AdapterLayer.RUNTIME_PROTOCOL,
            AdapterLayer.DEPLOYMENT_PROFILE,
            AdapterLayer.OUTPUT_NORMALIZER,
        ),
        artifact_digest=sha256_digest(
            {
                "adapter": "mie.adapter.ollama-chat",
                "version": "0.3.0",
                "layers": [item.value for item in AdapterLayer],
            }
        ),
        reviewed=True,
        configurable=True,
        required_permissions=("network:configured-runtime-endpoint",),
    )
