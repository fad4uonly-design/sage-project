"""Secrets manager tests."""

from __future__ import annotations

import pytest
from sage.core.engine import SageEngine
from sage.secrets.crypto import SecretBox
from sage.secrets.interfaces import SecretsManager


def test_secret_box_roundtrip() -> None:
    box = SecretBox("test-master-key-for-unit-tests")
    sealed = box.seal("super-secret-value")
    assert box.open(sealed) == "super-secret-value"


def test_secret_box_tamper_fails() -> None:
    box = SecretBox("test-master-key-for-unit-tests")
    sealed = box.seal("data")
    from sage.secrets.crypto import SealedSecret

    bad = SealedSecret(
        salt_b64=sealed.salt_b64,
        nonce_b64=sealed.nonce_b64,
        ciphertext_b64=sealed.ciphertext_b64[:-4] + "xxxx",
    )
    with pytest.raises(ValueError):
        box.open(bad)


@pytest.mark.asyncio
async def test_secrets_manager_store(engine: SageEngine) -> None:
    sm = engine.container.resolve(SecretsManager)  # type: ignore[type-abstract]
    await sm.set_secret("demo_key", "demo_value", metadata={"env": "test"})
    assert await sm.has("demo_key")
    assert await sm.get_secret("demo_key") == "demo_value"
    keys = await sm.list_keys()
    assert "demo_key" in keys
    await sm.rotate("demo_key", "demo_value_v2")
    assert await sm.get_secret("demo_key") == "demo_value_v2"
    assert await sm.delete_secret("demo_key")
    assert not await sm.has("demo_key")
