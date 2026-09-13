"""Model artifact and identity — the *research object* description.

A :class:`ModelArtifact` is a specific, versioned, checkable model checkpoint.
It carries no runtime-specific loading logic; loaders translate it into the
normalized :class:`~sage_research.interfaces.model_loader.LoadedModel` contract.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .collections import ImmutableMap


class ModelFormat(StrEnum):
    """Serialization/container format of a model artifact.

    ``ORIGINAL`` denotes a model in its native, author-shipped format (for
    Pythia-70M that is the Hugging Face ``transformers``/PyTorch checkpoint).
    ``CONVERTED`` covers derived formats (GGUF, ONNX, ...) which are only
    reachable through loaders registered for them. The research layer never
    depends on any single runtime or container format.
    """

    ORIGINAL = "original"
    CONVERTED = "converted"


@dataclass(frozen=True)
class ModelIdentity:
    """Stable identity of a concrete, loaded model instance."""

    family: str
    name: str
    version: str
    source: str

    @property
    def slug(self) -> str:
        """Compact, human-readable unique key, e.g. ``pythia/pythia-70m@default``."""
        return f"{self.family}/{self.name}@{self.version}"

    def to_dict(self) -> dict[str, str]:
        return {
            "family": self.family,
            "name": self.name,
            "version": self.version,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, data: dict[str, str]) -> ModelIdentity:
        return cls(
            family=data["family"],
            name=data["name"],
            version=data["version"],
            source=data["source"],
        )


@dataclass(frozen=True)
class ModelArtifact:
    """Describes a target model artifact to load (the pre-loading declaration)."""

    name: str
    family: str = "pythia"
    version: str = "default"
    format: ModelFormat = ModelFormat.ORIGINAL
    source: str = "huggingface:EleutherAI/pythia-70m"
    checksum: str | None = None

    def to_identity(self) -> ModelIdentity:
        return ModelIdentity(
            family=self.family,
            name=self.name,
            version=self.version,
            source=self.source,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "family": self.family,
            "version": self.version,
            "format": self.format.value,
            "source": self.source,
            "checksum": self.checksum,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> ModelArtifact:
        return cls(
            name=str(data["name"]),
            family=str(data["family"]),
            version=str(data["version"]),
            format=ModelFormat(str(data["format"])),
            source=str(data["source"]),
            checksum=data.get("checksum") if data.get("checksum") is not None else None,
        )


@dataclass(frozen=True)
class LoadOptions:
    """Runtime-agnostic load options.

    Only well-known knobs are typed; anything runtime-specific goes through
    ``extra`` and the research layer must never depend on it.
    """

    revision: str | None = None
    device: str | None = "cpu"
    dtype: str | None = None
    extra: ImmutableMap = ImmutableMap()
