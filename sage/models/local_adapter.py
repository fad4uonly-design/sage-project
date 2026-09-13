"""Backward-compatibility re-export for LocalLanguageModel."""

from sage.models.local._adapter import LocalLanguageModel, _extract_final_content

__all__ = ["LocalLanguageModel", "_extract_final_content"]
