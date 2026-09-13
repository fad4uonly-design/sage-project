"""
Local encryption helpers for secrets.

Uses Fernet-equivalent construction via stdlib only:
  PBKDF2-HMAC-SHA256 → AES-like stream via XOR of SHA-256 keystream
  (sufficient for local personal OS; can swap to cryptography.Fernet later).

For production hardening, install `cryptography` and prefer Fernet.
We intentionally keep a pure-stdlib path so SAGE stays dependency-light offline.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets as pysecrets
from dataclasses import dataclass


def _derive_key(password: bytes, salt: bytes, *, iterations: int = 200_000) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password, salt, iterations, dklen=32)


def _keystream(key: bytes, nonce: bytes, length: int) -> bytes:
    """HMAC-SHA256 counter mode keystream."""
    out = bytearray()
    counter = 0
    while len(out) < length:
        block = hmac.new(key, nonce + counter.to_bytes(8, "big"), hashlib.sha256).digest()
        out.extend(block)
        counter += 1
    return bytes(out[:length])


def _xor(data: bytes, stream: bytes) -> bytes:
    return bytes(a ^ b for a, b in zip(data, stream, strict=True))


@dataclass(frozen=True, slots=True)
class SealedSecret:
    salt_b64: str
    nonce_b64: str
    ciphertext_b64: str


class SecretBox:
    """Seal/open secrets with a master passphrase."""

    def __init__(self, master_key: str | bytes) -> None:
        if isinstance(master_key, str):
            master_key = master_key.encode("utf-8")
        if not master_key:
            raise ValueError("master_key must not be empty")
        self._master = master_key

    def seal(self, plaintext: str) -> SealedSecret:
        salt = pysecrets.token_bytes(16)
        nonce = pysecrets.token_bytes(16)
        key = _derive_key(self._master, salt)
        data = plaintext.encode("utf-8")
        stream = _keystream(key, nonce, len(data))
        ct = _xor(data, stream)
        # Integrity tag
        tag = hmac.new(key, nonce + ct, hashlib.sha256).digest()
        payload = tag + ct
        return SealedSecret(
            salt_b64=base64.urlsafe_b64encode(salt).decode("ascii"),
            nonce_b64=base64.urlsafe_b64encode(nonce).decode("ascii"),
            ciphertext_b64=base64.urlsafe_b64encode(payload).decode("ascii"),
        )

    def open(self, sealed: SealedSecret) -> str:
        salt = base64.urlsafe_b64decode(sealed.salt_b64.encode("ascii"))
        nonce = base64.urlsafe_b64decode(sealed.nonce_b64.encode("ascii"))
        payload = base64.urlsafe_b64decode(sealed.ciphertext_b64.encode("ascii"))
        if len(payload) < 32:
            raise ValueError("corrupt ciphertext")
        tag, ct = payload[:32], payload[32:]
        key = _derive_key(self._master, salt)
        expected = hmac.new(key, nonce + ct, hashlib.sha256).digest()
        if not hmac.compare_digest(tag, expected):
            raise ValueError("authentication failed — wrong master key or tampered data")
        stream = _keystream(key, nonce, len(ct))
        data = _xor(ct, stream)
        return data.decode("utf-8")


def generate_master_key() -> str:
    """Return a high-entropy master key suitable for first-run setup."""
    return base64.urlsafe_b64encode(os.urandom(32)).decode("ascii")
