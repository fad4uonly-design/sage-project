"""Model loading boundary (MIE/ARENA boundary).

A :class:`ModelLoader` turns a :class:`~sage_research.domain.model_artifact.ModelArtifact`
into a normalized :class:`LoadedModel`. The research layer only ever sees the
``LoadedModel`` contract, never the underlying runtime.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from typing import Protocol

from ..domain.architecture_map import ModuleInfo, ParameterInfo
from ..domain.collections import ImmutableMap
from ..domain.model_artifact import LoadOptions, ModelArtifact, ModelIdentity


class LoadedModel(Protocol):
    """Normalized model capability surface consumed by the research layer.

    Implementations translate whatever runtime they use (PyTorch/transformers,
    GGUF, ONNX, a remote service, ...) into this contract. The research layer
    never imports a runtime.
    """

    @property
    def identity(self) -> ModelIdentity: ...

    @property
    def config(self) -> ImmutableMap: ...

    def parameters(self) -> Iterator[ParameterInfo]: ...

    def modules(self) -> Iterator[ModuleInfo]: ...


class ModelLoader(ABC):
    """Loads a model artifact into a normalized :class:`LoadedModel`."""

    @abstractmethod
    def load(self, artifact: ModelArtifact, options: LoadOptions | None = None) -> LoadedModel:
        """Resolve ``artifact`` into a normalized loaded model.

        Raises:
            ValueError: if the artifact/format is not supported by this loader.
        """
        raise NotImplementedError
