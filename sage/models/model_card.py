"""ModelCard: a structured description of any model or tool SAGE can call.

This is the single source of truth the ValueRouter reads from when deciding
which model tier to use for a given task (``sage/core/value_router.py``).
Every field maps directly to the MODEL taxonomy from the Lean Intelligence
architecture (``docs`` / SAGE_ARCHITECTURE.md):

MODEL
 ├── Identity                (name, provider, version)
 ├── Architecture            (dense/MoE, param count, family)
 ├── Capabilities            (chat, code, vision, function-calling, etc.)
 ├── Reasoning               (none / chain-of-thought / extended thinking)
 ├── Tool Use                (native tool-calling support, format)
 ├── Context                 (max context window)
 ├── Memory Requirements     (VRAM/RAM to run it, if local)
 ├── Quantization            (fp16/int8/int4/GGUF variants supported)
 ├── Runtime Compatibility   (vLLM, llama.cpp, transformers, API-only...)
 ├── API Interface           (REST/gRPC, streaming support, endpoint shape)
 ├── License                 (open weights / commercial / proprietary API)
 ├── Strengths               (free text, structured tags)
 ├── Weaknesses              (free text, structured tags)
 ├── Cost                    ($ per 1M tokens, or local compute cost)
 └── Reliability             (uptime/consistency notes, failure modes)

Model choice becomes a first-class, inspectable decision instead of a
hardcoded call: registering a new model never touches router or call-site
code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ReasoningLevel(Enum):
    NONE = "none"                   # pattern-completion only, no CoT
    BASIC = "basic"                 # can do simple step-by-step if prompted
    CHAIN_OF_THOUGHT = "cot"        # reliable multi-step reasoning
    EXTENDED_THINKING = "extended"  # native extended/deliberate reasoning mode


class ToolUseSupport(Enum):
    NONE = "none"
    PROMPTED_ONLY = "prompted_only"     # can be coaxed via prompt, unreliable
    NATIVE_FUNCTION_CALLING = "native"  # first-class tool-calling API


class RuntimeTarget(Enum):
    API_ONLY = "api_only"
    VLLM = "vllm"
    LLAMA_CPP = "llama_cpp"
    TRANSFORMERS = "transformers"
    AIRLLM = "airllm"
    ONNX = "onnx"


@dataclass
class Identity:
    name: str
    provider: str
    version: str = "latest"
    #: Where model weights are pulled FROM: ``"huggingface"`` (Hugging Face
    #: Hub) or ``"ollama"`` (local Ollama registry). Additive default keeps
    #: existing ModelCard callers unchanged; the model-gate downloader
    #: dispatches on it (``sage/core/providers/model_download.py``).
    source: str = "huggingface"


@dataclass
class Architecture:
    family: str                      # e.g. "Qwen2.5", "Llama-3", "GPT"
    param_count_b: float | None      # billions of parameters; None if undisclosed
    style: str = "dense"             # "dense" | "moe"


@dataclass
class Capabilities:
    chat: bool = True
    code: bool = False
    vision: bool = False
    long_document: bool = False
    structured_output: bool = False
    multilingual: bool = False


@dataclass
class MemoryRequirements:
    min_vram_gb: float | None = None  # None => not a local model / N/A
    min_ram_gb: float | None = None
    notes: str = ""


@dataclass
class Cost:
    input_per_million_tokens_usd: float | None = None
    output_per_million_tokens_usd: float | None = None
    local_compute_notes: str = ""  # e.g. "free after hardware cost, ~40W draw"


@dataclass
class Reliability:
    uptime_notes: str = ""
    known_failure_modes: list[str] = field(default_factory=list)
    consistency: str = "unknown"  # "high" | "medium" | "low" | "unknown"


@dataclass
class ModelCard:
    identity: Identity
    architecture: Architecture
    capabilities: Capabilities
    reasoning: ReasoningLevel
    tool_use: ToolUseSupport
    context_window_tokens: int
    memory_requirements: MemoryRequirements
    quantization_supported: list[str]  # e.g. ["fp16", "int8", "int4", "gguf-q4_k_m"]
    runtime_compatibility: list[RuntimeTarget]
    api_interface: str                 # short description of the calling convention
    license: str
    strengths: list[str]
    weaknesses: list[str]
    cost: Cost
    reliability: Reliability

    @property
    def is_local(self) -> bool:
        return (
            RuntimeTarget.API_ONLY not in self.runtime_compatibility
            or len(self.runtime_compatibility) > 1
        )

    @property
    def cheap_tier(self) -> bool:
        """Rough router heuristic: worth reaching for by default, before
        escalating. Small param count OR near-zero marginal API cost."""
        small = (self.architecture.param_count_b or 999) <= 8
        cheap_api = (self.cost.input_per_million_tokens_usd or 999) <= 0.5
        return small or cheap_api

    def summary(self) -> str:
        return (
            f"{self.identity.name} ({self.identity.provider}) — "
            f"{self.architecture.param_count_b or '?'}B params, "
            f"reasoning={self.reasoning.value}, tools={self.tool_use.value}, "
            f"ctx={self.context_window_tokens}"
        )
