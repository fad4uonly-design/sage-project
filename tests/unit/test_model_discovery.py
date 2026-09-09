"""Unit tests for ModelDiscoverer — fake SearchFn, mocked hardware.

These prove the HARD hardware filter: over-budget candidates (VRAM, RAM, or
GPU-required on a GPU-less box) are EXCLUDED entirely, never proposed.
"""

from __future__ import annotations

from sage.core.hardware_profiler import HardwareProfile
from sage.core.model_discovery import ModelDiscoverer, ModelMetadata, fits_hardware
from sage.models.model_card import (
    Architecture,
    Capabilities,
    Cost,
    Identity,
    MemoryRequirements,
    ModelCard,
    ReasoningLevel,
    Reliability,
    RuntimeTarget,
    ToolUseSupport,
)

GPU_BOX = HardwareProfile(
    gpu_available=True, vram_gb=2.0, ram_gb=15.6, cpu_cores=12, free_disk_gb=282.0
)
CPU_ONLY = HardwareProfile(
    gpu_available=False, vram_gb=None, ram_gb=15.6, cpu_cores=12, free_disk_gb=282.0
)

TINY = ModelMetadata(
    name="tiny-local-1.5b",
    provider="huggingface",
    family="Qwen2.5",
    param_count_b=1.5,
    capabilities={"chat", "code"},
    reasoning="basic",
    tool_use="prompted_only",
    context_window_tokens=8192,
    min_vram_gb=1.0,
    min_ram_gb=4.0,
    quantization_supported=["int4"],
    runtime_compatibility=["llama_cpp"],
    api_interface="local process, OpenAI-compatible",
    license="Apache 2.0",
    consistency="medium",
    strengths=["fast", "cheap"],
    weaknesses=["weak reasoning"],
    source_url="https://huggingface.co/tiny/local-1.5b",
)
HUGE = ModelMetadata(
    name="huge-70b",
    provider="huggingface",
    family="Llama-3",
    param_count_b=70.0,
    capabilities={"chat"},
    reasoning="cot",
    tool_use="native",
    context_window_tokens=128000,
    min_vram_gb=40.0,
    min_ram_gb=128.0,
    runtime_compatibility=["vllm"],
    license="meta",
    source_url="https://huggingface.co/huge/70b",
)
RAM_HOG = ModelMetadata(
    name="ram-hog-32b",
    provider="huggingface",
    family="Qwen",
    param_count_b=32.0,
    capabilities={"chat"},
    reasoning="cot",
    tool_use="native",
    context_window_tokens=64000,
    min_vram_gb=0.0,  # CPU-only in VRAM terms...
    min_ram_gb=64.0,  # ...but 64 GiB RAM > 15.6 available
    runtime_compatibility=["transformers"],
    license="Apache 2.0",
    source_url="https://example/ram-hog",
)
GPU_DEPENDENT = ModelMetadata(
    name="gpu-required-8b",
    provider="ollama",
    family="Qwen2.5",
    param_count_b=8.0,
    capabilities={"chat"},
    reasoning="cot",
    tool_use="native",
    context_window_tokens=32768,
    min_vram_gb=6.0,
    min_ram_gb=8.0,
    runtime_compatibility=["ollama"],
    license="Apache 2.0",
    source_url="https://ollama.local/8b",
)


class FakeSearcher:
    def __init__(self, results: list[ModelMetadata]) -> None:
        self.results = results
        self.calls: list[str] = []

    async def __call__(self, need: str) -> list[ModelMetadata]:
        self.calls.append(need)
        return list(self.results)


async def test_discover_hard_filters_over_budget_models() -> None:
    searcher = FakeSearcher([TINY, HUGE, RAM_HOG])
    discoverer = ModelDiscoverer(searcher)

    proposals = await discoverer.discover("fast local coding model", GPU_BOX)

    names = {p.model_card.identity.name for p in proposals}
async def test_discover_builds_full_model_card_from_metadata() -> None:
    searcher = FakeSearcher([TINY])
    discoverer = ModelDiscoverer(searcher)

    proposals = await discoverer.discover("fast local coding model", GPU_BOX)
    assert len(proposals) == 1
    card = proposals[0].model_card

    assert card.identity.name == "tiny-local-1.5b"
    assert card.identity.provider == "huggingface"
    assert card.architecture.param_count_b == 1.5
    assert card.capabilities.code is True
    assert card.reasoning is ReasoningLevel.BASIC
    assert card.tool_use is ToolUseSupport.PROMPTED_ONLY
    assert card.context_window_tokens == 8192
    assert card.memory_requirements.min_vram_gb == 1.0
    assert card.memory_requirements.min_ram_gb == 4.0
    assert card.quantization_supported == ["int4"]
    assert card.runtime_compatibility == [RuntimeTarget.LLAMA_CPP]
    assert card.license == "Apache 2.0"
    assert card.cost is not None
    assert card.reliability.consistency == "medium"

    proposal = proposals[0]
    assert proposal.status == "candidate"
    assert proposal.source_url == TINY.source_url
    assert proposal.discovered_at.tzinfo is not None
    assert "VRAM 1 <= 2 GiB" in proposal.hardware_fit_notes
    assert "RAM 4 <= 15.6 GiB" in proposal.hardware_fit_notes


async def test_discover_passes_need_to_searcher() -> None:
    searcher = FakeSearcher([TINY])
    discoverer = ModelDiscoverer(searcher)
    await discoverer.discover("  fast local coding model  ", GPU_BOX)
    assert searcher.calls == ["fast local coding model"]


async def test_discover_no_results_returns_empty() -> None:
    searcher = FakeSearcher([])
    discoverer = ModelDiscoverer(searcher)
    assert await discoverer.discover("anything", GPU_BOX) == []


async def test_discover_rejects_blank_need() -> None:
    searcher = FakeSearcher([TINY])
    discoverer = ModelDiscoverer(searcher)
    try:
        await discoverer.discover("   ", GPU_BOX)
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for blank need")
    assert searcher.calls == []


def test_fits_hardware_helper_direct() -> None:
    card = ModelCard(
        identity=Identity(name="m", provider="p"),
        architecture=Architecture(family="f", param_count_b=1.0),
        capabilities=Capabilities(),
        reasoning=ReasoningLevel.NONE,
        tool_use=ToolUseSupport.NONE,
        context_window_tokens=1000,
        memory_requirements=MemoryRequirements(min_vram_gb=1.5, min_ram_gb=8.0),
        quantization_supported=[],
        runtime_compatibility=[RuntimeTarget.LLAMA_CPP],
        api_interface="",
        license="",
        strengths=[],
        weaknesses=[],
        cost=Cost(),
        reliability=Reliability(),
    )
    ok = ModelCard(
        identity=Identity(name="m2", provider="p"),
        architecture=Architecture(family="f", param_count_b=0.5),
        capabilities=Capabilities(),
        reasoning=ReasoningLevel.NONE,
        tool_use=ToolUseSupport.NONE,
        context_window_tokens=1000,
        memory_requirements=MemoryRequirements(min_vram_gb=1.0, min_ram_gb=4.0),
        quantization_supported=[],
        runtime_compatibility=[RuntimeTarget.LLAMA_CPP],
        api_interface="",
        license="",
        strengths=[],
        weaknesses=[],
        cost=Cost(),
        reliability=Reliability(),
    )
    over_vram = HardwareProfile(gpu_available=True, vram_gb=1.0, ram_gb=32.0, cpu_cores=8, free_disk_gb=10.0)
    assert fits_hardware(ok, GPU_BOX) is None
    assert fits_hardware(card, over_vram) is not None
    assert "VRAM" in fits_hardware(card, over_vram)
    low_ram = HardwareProfile(gpu_available=True, vram_gb=8.0, ram_gb=4.0, cpu_cores=8, free_disk_gb=10.0)
    assert "RAM" in fits_hardware(ok, low_ram)
    no_gpu = HardwareProfile(gpu_available=False, vram_gb=None, ram_gb=32.0, cpu_cores=8, free_disk_gb=10.0)
    assert "GPU" in fits_hardware(ok, no_gpu)
    unknown_vram = HardwareProfile(gpu_available=True, vram_gb=None, ram_gb=32.0, cpu_cores=8, free_disk_gb=10.0)
    assert "unknown" in fits_hardware(ok, unknown_vram)
    assert names == {"tiny-local-1.5b"}
    assert "huge-70b" not in names, "40 GiB VRAM model must not be proposed on a 2 GiB box"
    assert "ram-hog-32b" not in names, "64 GiB RAM model must not be proposed on 15.6 GiB"
    for proposal in proposals:
        assert proposal.status == "candidate"


async def test_discover_filters_gpu_required_models_when_no_gpu() -> None:
    searcher = FakeSearcher([TINY, GPU_DEPENDENT])
    discoverer = ModelDiscoverer(searcher)

    proposals = await discoverer.discover("local chat", CPU_ONLY)

    names = {p.model_card.identity.name for p in proposals}
    assert names == {"tiny-local-1.5b"}
    assert "gpu-required-8b" not in names