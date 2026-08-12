from __future__ import annotations

from model_integration_engine.contracts import DiscoveryProvider, RuntimeAdapter
from model_integration_engine.domain import PluginDescriptor, TrustState


class FakeDiscovery:
    descriptor = PluginDescriptor(
        plugin_id="test.discovery",
        plugin_version="1.0.0",
        contract_version="0.1.0",
        operations=("discover",),
        trust_state=TrustState.REVIEW_REQUIRED,
    )

    async def discover(self, request, context):
        if False:
            yield None


class IncompleteRuntimeAdapter:
    pass


def test_discovery_protocol_is_runtime_checkable() -> None:
    assert isinstance(FakeDiscovery(), DiscoveryProvider)


def test_incomplete_runtime_adapter_does_not_satisfy_contract() -> None:
    assert not isinstance(IncompleteRuntimeAdapter(), RuntimeAdapter)
