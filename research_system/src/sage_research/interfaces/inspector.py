"""Architecture inspection boundary."""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..domain.architecture_map import ArchitectureMap
from .model_loader import LoadedModel


class ArchitectureInspector(ABC):
    """Produces an :class:`ArchitectureMap` from a normalized loaded model."""

    @abstractmethod
    def inspect(self, model: LoadedModel, *, timestamp_utc: str | None = None) -> ArchitectureMap:
        """Inspect ``model`` and return a structured architecture map."""
        raise NotImplementedError
