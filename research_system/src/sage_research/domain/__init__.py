"""Core domain structures.

Rules for this package:

* Pure data + invariants only. No I/O, no runtime imports (torch/transformers),
  no model-specific business logic.
* Evidence-bearing values are immutable (frozen dataclasses, tuples, ImmutableMap).
* This layer must never depend on ``infrastructure`` or ``experiments``.
"""
