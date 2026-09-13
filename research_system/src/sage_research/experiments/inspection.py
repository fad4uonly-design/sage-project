"""Architecture-inspection experiment (Research Specimen 001).

Orchestrates the milestone slice end-to-end:

    Model artifact -> model loading boundary -> architecture inspection
    -> architecture map -> Model Knowledge records -> persistence.

All three dependencies (loader, inspector, repository) are injected, so the
experiment is runtime-agnostic and fully deterministic given an injected clock.
"""

from __future__ import annotations

import hashlib
import platform
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from ..domain.architecture_map import ArchitectureMap
from ..domain.collections import ImmutableMap
from ..domain.knowledge import KnowledgeRecord, utcnow_iso
from ..domain.model_artifact import LoadOptions, ModelArtifact, ModelIdentity
from ..interfaces.inspector import ArchitectureInspector
from ..interfaces.model_loader import ModelLoader
from ..interfaces.repository import KnowledgeRepository
from ..version import __version__
from .model_knowledge import build_model_knowledge


@dataclass(frozen=True)
class EnvironmentInfo:
    """Environment facts recorded for reproducibility."""

    system_version: str
    python_version: str
    platform: str
    libraries: ImmutableMap

    def to_dict(self) -> dict[str, object]:
        return {
            "system_version": self.system_version,
            "python_version": self.python_version,
            "platform": self.platform,
            "libraries": self.libraries.to_dict(),
        }


@dataclass(frozen=True)
class InspectionReport:
    """The immutable result of one architecture-inspection run."""

    report_id: str
    artifact: ModelArtifact
    identity: ModelIdentity
    architecture_map: ArchitectureMap
    knowledge_records: tuple[KnowledgeRecord, ...]
    environment: EnvironmentInfo
    started_utc: str
    completed_utc: str
    rerun_configuration: ImmutableMap

    def to_dict(self) -> dict[str, object]:
        return {
            "report_id": self.report_id,
            "artifact": self.artifact.to_dict(),
            "identity": self.identity.to_dict(),
            "architecture_map": self.architecture_map.to_dict(),
            "knowledge_records": [r.to_dict() for r in self.knowledge_records],
            "environment": self.environment.to_dict(),
            "started_utc": self.started_utc,
            "completed_utc": self.completed_utc,
            "rerun_configuration": self.rerun_configuration.to_dict(),
        }


def stable_report_id(artifact: ModelArtifact, started_utc: str) -> str:
    digest = hashlib.sha256(
        f"{artifact.to_identity().slug}|{started_utc}".encode()
    ).hexdigest()
    return f"rpt-{digest[:24]}"


class ModelInspectionExperiment:
    """Runs the architecture-inspection experiment.

    Args:
        loader: model loader (port).
        inspector: architecture inspector (port).
        repository: knowledge repository (port).
        system_version: recorded in every knowledge record (defaults to the
            package version).
        clock: injectable UTC-now callable for deterministic tests.
    """

    def __init__(
        self,
        loader: ModelLoader,
        inspector: ArchitectureInspector,
        repository: KnowledgeRepository,
        *,
        system_version: str = __version__,
        clock: Callable[[], str] | None = None,
    ) -> None:
        self._loader = loader
        self._inspector = inspector
        self._repository = repository
        self._system_version = system_version
        self._clock = clock or utcnow_iso

    def run(
        self,
        artifact: ModelArtifact,
        *,
        options: LoadOptions | None = None,
        rerun_configuration: Mapping[str, object] | None = None,
    ) -> InspectionReport:
        started = self._clock()
        environment = _capture_environment(self._system_version)

        loaded = self._loader.load(artifact, options)
        amap = self._inspector.inspect(loaded, timestamp_utc=started)

        report_id = stable_report_id(artifact, started)
        records = build_model_knowledge(amap, report_id, self._system_version, started)
        for record in records:
            self._repository.save(record)

        completed = self._clock()
        return InspectionReport(
            report_id=report_id,
            artifact=artifact,
            identity=loaded.identity,
            architecture_map=amap,
            knowledge_records=records,
            environment=environment,
            started_utc=started,
            completed_utc=completed,
            rerun_configuration=ImmutableMap(rerun_configuration or {}),
        )


def _capture_environment(system_version: str) -> EnvironmentInfo:
    libraries = {
        name: _package_version(name)
        for name in ("torch", "transformers", "safetensors", "numpy")
    }
    return EnvironmentInfo(
        system_version=system_version,
        python_version=sys.version.split()[0],
        platform=platform.platform(),
        libraries=ImmutableMap(libraries),
    )


def _package_version(name: str) -> str:
    try:
        from importlib.metadata import version

        return version(name)
    except Exception:
        return "not_installed"
