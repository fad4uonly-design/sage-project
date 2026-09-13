"""Generative-model ports — the *capability* boundary for the model bench.

The architecture-inspection path only ever *reads* a model (parameters and
modules). The bench additionally needs to *run* it, so this module defines the
minimal generative port. As with :mod:`~sage_research.interfaces.model_loader`,
the research layer never imports a runtime; adapters translate PyTorch, GGUF,
or a remote service into :class:`GenerativeModelHandle`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Protocol

from ..domain.model_artifact import LoadOptions, ModelArtifact
from .model_loader import ModelIdentity


class GenerativeModelHandle(Protocol):
    """Normalized generate-capability surface consumed by the bench."""

    @property
    def identity(self) -> ModelIdentity: ...

    def generate(self, prompt: str, *, max_new_tokens: int = 40) -> str:
        """Continue ``prompt`` with at most ``max_new_tokens`` new tokens."""
        ...


class GenerativeModelLoader(ABC):
    """Loads a model artifact into a :class:`GenerativeModelHandle`."""

    @abstractmethod
    def load(
        self,
        artifact: ModelArtifact,
        options: LoadOptions | None = None,
    ) -> GenerativeModelHandle:
        """Resolve ``artifact`` into a generative handle.

        Raises:
            ValueError: if the artifact/format is not supported by this loader.
        """
        raise NotImplementedError
