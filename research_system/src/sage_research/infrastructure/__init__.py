"""Infrastructure adapters (runtime and persistence).

Everything here translates between the outside world and the domain/interfaces.
Nothing here contains research logic, and the domain layer never imports it.
"""

from .in_memory_repository import InMemoryKnowledgeRepository
from .json_repository import JsonKnowledgeRepository
from .pytorch_loader import PyTorchLoadedModel, PyTorchModelLoader

__all__ = [
    "InMemoryKnowledgeRepository",
    "JsonKnowledgeRepository",
    "PyTorchModelLoader",
    "PyTorchLoadedModel",
]
