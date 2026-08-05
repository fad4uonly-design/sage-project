"""Shared utilities for SAGE."""

from sage.utils.ids import new_id
from sage.utils.result import Err, Ok, Result
from sage.utils.time import utcnow, utcnow_iso

__all__ = [
    "new_id",
    "utcnow",
    "utcnow_iso",
    "Result",
    "Ok",
    "Err",
]
