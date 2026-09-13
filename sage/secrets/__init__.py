"""Secrets Manager — encrypted local credential storage."""

from sage.secrets.interfaces import SecretsManager
from sage.secrets.service import SecretsModule

__all__ = ["SecretsManager", "SecretsModule"]
