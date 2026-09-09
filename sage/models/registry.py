"""ModelRegistry: holds every ModelCard SAGE knows about and answers
"what's the cheapest sufficient model for this requirement set?"

Populate this with your real, current options — the three cards below
(a tiny local model, a mid local model, and a frontier API model) are
illustrative placeholders showing the shape of a real entry, not a live
catalog. Swap in actual Qwen/local/AirLLM configs and whatever API models
SAGE uses. Registering a new model never touches router or call-site code:

    registry = ModelRegistry()
    registry.add(my_new_card)
"""

from __future__ import annotations

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


def _example_cards() -> list[ModelCard]:
    tiny_local = ModelCard(
        identity=Identity(name="Qwen2.5-1.5B-Instruct", provider="local"),
        architecture=Architecture(family="Qwen2.5", param_count_b=1.5, style="dense"),
        capabilities=Capabilities(chat=True, code=True, structured_output=True),
        reasoning=ReasoningLevel.BASIC,
        tool_use=ToolUseSupport.PROMPTED_ONLY,
        context_window_tokens=32_000,
        memory_requirements=MemoryRequirements(
            min_vram_gb=2, min_ram_gb=4, notes="runs int4 on CPU-only boxes"
        ),
        quantization_supported=["fp16", "int8", "gguf-q4_k_m"],
        runtime_compatibility=[RuntimeTarget.LLAMA_CPP, RuntimeTarget.TRANSFORMERS],
        api_interface="local process, OpenAI-compatible if served via llama.cpp server",
        license="Apache 2.0",
        strengths=[
            "near-zero marginal cost",
            "very low latency",
            "good for routing/classification itself",
        ],
        weaknesses=[
            "weak multi-step reasoning",
            "unreliable tool-call formatting",
            "short-context tasks only",
        ],
        cost=Cost(local_compute_notes="electricity only, ~5-15W"),
        reliability=Reliability(
            consistency="medium",
            known_failure_modes=["hallucinates on anything requiring real reasoning"],
        ),
    )

    mid_local = ModelCard(
        identity=Identity(name="Qwen2.5-14B-Instruct", provider="local"),
        architecture=Architecture(family="Qwen2.5", param_count_b=14, style="dense"),
        capabilities=Capabilities(
            chat=True, code=True, structured_output=True, multilingual=True
        ),
        reasoning=ReasoningLevel.CHAIN_OF_THOUGHT,
        tool_use=ToolUseSupport.NATIVE_FUNCTION_CALLING,
        context_window_tokens=128_000,
        memory_requirements=MemoryRequirements(
            min_vram_gb=16, min_ram_gb=32, notes="int4 fits on a single 16-24GB GPU"
        ),
        quantization_supported=["fp16", "int8", "int4", "gguf-q4_k_m", "gguf-q5_k_m"],
        runtime_compatibility=[
            RuntimeTarget.VLLM,
            RuntimeTarget.LLAMA_CPP,
            RuntimeTarget.AIRLLM,
        ],
        api_interface="OpenAI-compatible via vLLM server",
        license="Apache 2.0",
        strengths=[
            "solid general reasoning",
            "reliable structured output",
            "good cost/capability ratio for a home rig",
        ],
        weaknesses=[
            "slower than tiny tier",
            "still behind frontier on hard multi-hop reasoning",
        ],
        cost=Cost(
            local_compute_notes="electricity + hardware amortization, ~150-300W under load"
        ),
        reliability=Reliability(consistency="high"),
    )

    frontier_api = ModelCard(
        identity=Identity(name="Claude Sonnet 5", provider="Anthropic"),
        architecture=Architecture(family="Claude", param_count_b=None, style="dense"),
        capabilities=Capabilities(
            chat=True,
            code=True,
            vision=True,
            long_document=True,
            structured_output=True,
            multilingual=True,
        ),
        reasoning=ReasoningLevel.EXTENDED_THINKING,
        tool_use=ToolUseSupport.NATIVE_FUNCTION_CALLING,
        context_window_tokens=200_000,
        memory_requirements=MemoryRequirements(notes="N/A - API only"),
        quantization_supported=[],
        runtime_compatibility=[RuntimeTarget.API_ONLY],
        api_interface="Anthropic Messages API (REST, streaming supported)",
        license="proprietary, commercial API",
        strengths=[
            "strong multi-step reasoning",
            "reliable tool use",
            "large context",
            "high output quality",
        ],
        weaknesses=[
            "highest marginal cost",
            "network dependency/latency",
            "overkill for trivial lookups",
        ],
        cost=Cost(input_per_million_tokens_usd=3.0, output_per_million_tokens_usd=15.0),
        reliability=Reliability(
            consistency="high", uptime_notes="depends on Anthropic API availability"
        ),
    )

    return [tiny_local, mid_local, frontier_api]


class ModelRegistry:
    def __init__(self, cards: list[ModelCard] | None = None) -> None:
        self.cards: list[ModelCard] = cards if cards is not None else _example_cards()

    def add(self, card: ModelCard) -> None:
        self.cards.append(card)

    def all(self) -> list[ModelCard]:
        return list(self.cards)

    def cheapest_sufficient(
        self,
        needs_reasoning: bool = False,
        needs_tools: bool = False,
        needs_long_context_tokens: int = 0,
        needs_vision: bool = False,
    ) -> ModelCard | None:
        """Return the cheapest ModelCard that satisfies the stated requirements.

        Ordering is by a crude cost proxy: local models first (smaller param
        count first), then API models by lower $/M input tokens.
        """
        candidates = [
            c
            for c in self.cards
            if self._satisfies(
                c, needs_reasoning, needs_tools, needs_long_context_tokens, needs_vision
            )
        ]
        if not candidates:
            return None

        def cost_key(c: ModelCard) -> tuple[int, float]:
            if c.identity.provider == "local":
                return (0, c.architecture.param_count_b or 0)
            return (1, c.cost.input_per_million_tokens_usd or 999)

        candidates.sort(key=cost_key)
        return candidates[0]

    @staticmethod
    def _satisfies(
        c: ModelCard,
        needs_reasoning: bool,
        needs_tools: bool,
        needs_long_context: int,
        needs_vision: bool,
    ) -> bool:
        if needs_reasoning and c.reasoning in (ReasoningLevel.NONE,):
            return False
        if needs_tools and c.tool_use != ToolUseSupport.NATIVE_FUNCTION_CALLING:
            # Prompted-only tool use is unreliable enough that it shouldn't
            # satisfy a genuine tool-use requirement -- this is exactly the
            # kind of "cheapest but wrong" mistake the router must not make.
            return False
        if needs_long_context and c.context_window_tokens < needs_long_context:
            return False
        if needs_vision:
            return c.capabilities.vision
        return True
