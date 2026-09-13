"""Model bench registry — small-model rows for the research harness.

Each row is a *declaration* of a model the bench can evaluate; nothing here
loads weights. The Pythia-70M row is the original Research Specimen 001
baseline; the remaining rows are the small models the SOUP/Evolver loop
compares against.

``hf_candidates`` lists Hugging Face repo ids in preference order. The loader
tries them in order, so a row can prefer a newer release (e.g. OLMo 3) while
remaining runnable on a verified fallback (e.g. OLMo 2) before the newer id
is confirmed.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class BenchModel:
    """One model the bench can load and evaluate."""

    key: str
    name: str
    family: str
    hf_candidates: tuple[str, ...]
    parameter_hint: str
    notes: str = ""
    eval_suite: str = "tinystories"
    tags: tuple[str, ...] = field(default_factory=tuple)

    @property
    def primary_source(self) -> str:
        return f"huggingface:{self.hf_candidates[0]}"

    def to_dict(self) -> dict[str, object]:
        return {
            "key": self.key,
            "name": self.name,
            "family": self.family,
            "hf_candidates": list(self.hf_candidates),
            "parameter_hint": self.parameter_hint,
            "notes": self.notes,
            "eval_suite": self.eval_suite,
            "tags": list(self.tags),
        }


MODEL_REGISTRY: tuple[BenchModel, ...] = (
    BenchModel(
        key="pythia-70m",
        name="Pythia-70M",
        family="pythia",
        hf_candidates=("EleutherAI/pythia-70m",),
        parameter_hint="~70M",
        notes=(
            "Research Specimen 001 — the original architecture-inspection "
            "baseline. Reference values are asserted by the integration test."
        ),
        tags=("baseline", "gpt-neox"),
    ),
    BenchModel(
        key="gpt2-small",
        name="GPT-2 Small",
        family="gpt2",
        hf_candidates=("openai-community/gpt2", "gpt2"),
        parameter_hint="~124M",
        notes=(
            "The canonical simple baseline. Retained so every experiment can "
            "be regression-compared against a well-understood transformer."
        ),
        tags=("baseline", "gpt2"),
    ),
    BenchModel(
        key="openelm-270m",
        name="OpenELM-270M",
        family="openelm",
        hf_candidates=("apple/OpenELM-270M",),
        parameter_hint="~270M",
        notes=(
            "Efficient-architecture reference (layer-wise scaling). Note: "
            "OpenELM checkpoints ship without a bundled tokenizer config; "
            "the loader pairs them with a matching tokenizer repo when needed."
        ),
        tags=("efficient-architecture",),
    ),
    BenchModel(
        key="olmo-3",
        name="OLMo 3",
        family="olmo",
        # Prefer the OLMo 3 release; fall back to the verified OLMo 2 1B id
        # until the OLMo 3 repo id is confirmed against the AllenAI catalog.
        hf_candidates=("allenai/OLMo-3-1B", "allenai/OLMo-2-0425-1B"),
        parameter_hint="~1B",
        notes=(
            "Fully open training data + checkpoints. The candidate list keeps "
            "the bench runnable on OLMo 2 while OLMo 3 availability is verified."
        ),
        tags=("open-data",),
    ),
    BenchModel(
        key="smollm2-135m",
        name="SmolLM2-135M",
        family="smollm2",
        hf_candidates=("HuggingFaceTB/SmolLM2-135M",),
        parameter_hint="~135M",
        notes=(
            "Small, recent, well-behaved instruction+prose model; a strong "
            "cheap challenger for TinyStories-style smoke evaluation."
        ),
        tags=("challenger",),
    ),
    BenchModel(
        key="qwen2.5-0.5b",
        name="Qwen2.5-0.5B",
        family="qwen2.5",
        hf_candidates=("Qwen/Qwen2.5-0.5B",),
        parameter_hint="~0.5B",
        notes="Brain-capability reference model (small tier).",
        tags=("challenger", "brain"),
    ),
    BenchModel(
        key="qwen3-0.6b",
        name="Qwen3-0.6B",
        family="qwen3",
        hf_candidates=("Qwen/Qwen3-0.6B",),
        parameter_hint="~0.6B",
        notes="Newest brain-capability reference model (small tier).",
        tags=("challenger", "brain"),
    ),
)


def get_model(key: str) -> BenchModel:
    """Look up a registry row by key (raises KeyError when unknown)."""
    for model in MODEL_REGISTRY:
        if model.key == key:
            return model
    raise KeyError(
        f"Unknown bench model {key!r}; known keys: "
        + ", ".join(m.key for m in MODEL_REGISTRY)
    )


def iter_models() -> tuple[BenchModel, ...]:
    """All registry rows in declaration order."""
    return MODEL_REGISTRY
