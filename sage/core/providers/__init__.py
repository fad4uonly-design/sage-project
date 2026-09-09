"""Real provider implementations wired into SAGE's DI slots.

These modules turn the injectable DI slots (``SearchFn``,
``DownloadFn``) from abstractions into real implementations:

* ``duckduckgo_search`` — DuckDuckGo-style web search, no API key; backs
  both WebLearner and ModelDiscoverer default searcher slots.
* ``model_download`` — Hugging Face Hub + Ollama model downloads,
  consumed by the model-approval gate after a model has already been
  approved (``sage/core/model_gate.py``).

None of these modules change the public signatures defined in
``web_learner.py`` / ``model_discovery.py`` / ``model_gate.py``.
"""

from __future__ import annotations

__all__ = [
    "duckduckgo_search",
    "model_download",
]
