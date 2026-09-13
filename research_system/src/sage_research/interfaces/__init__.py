"""Clean contracts (ports) between the research layer and the outside world.

These are the MIE/ARENA boundary: the research system consumes *normalized*
model capabilities and never couples to Ollama, GGUF, Qwen, Transformers
internals, or any single runtime. The eventual SAGE integration will go through
the existing Model Integration Engine contracts, which adapt to these ports.
"""

from .inspector import ArchitectureInspector
from .model_loader import LoadedModel, ModelLoader
from .repository import KnowledgeRepository

__all__ = [
    "LoadedModel",
    "ModelLoader",
    "ArchitectureInspector",
    "KnowledgeRepository",
]
