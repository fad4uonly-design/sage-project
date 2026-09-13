"""Deterministic fake model for unit tests (no torch required).

Mirrors a GPT-NeoX-shaped module tree (the Pythia family) so the heuristic
inspector can be exercised end-to-end without any runtime dependency.
"""

from __future__ import annotations

from collections.abc import Iterator

from sage_research.domain.architecture_map import ModuleInfo, ParameterInfo
from sage_research.domain.collections import ImmutableMap
from sage_research.domain.model_artifact import ModelIdentity

HIDDEN = 16
VOCAB = 64
LAYERS = 2
HEADS = 2
INTERMEDIATE = 32

DEFAULT_CONFIG = {
    "model_type": "fake_gpt_neox",
    "architectures": ["FakeForCausalLM"],
    "hidden_size": HIDDEN,
    "num_hidden_layers": LAYERS,
    "num_attention_heads": HEADS,
    "vocab_size": VOCAB,
    "intermediate_size": INTERMEDIATE,
    "layer_norm_eps": 1e-5,
}

# Expected values derived from the fake model (kept here so tests stay in sync).
EXPECTED_TOTAL_PARAMETERS = 6304
EXPECTED_NUM_COMPONENTS = 17   # 15 leaf components + 2 blocks
EXPECTED_NUM_CONNECTIONS = 13  # 3 forward-chain + 10 intra-block
EXPECTED_NUM_RECORDS = 27      # 1 identity + 9 summary facts + 17 component claims


def _numel(shape) -> int:
    n = 1
    for dim in shape:
        n *= dim
    return n


def build_params() -> list[ParameterInfo]:
    specs = [("model.embed_in.weight", (VOCAB, HIDDEN))]
    for layer in range(LAYERS):
        p = f"model.layers.{layer}"
        specs.extend(
            [
                (f"{p}.input_layernorm.weight", (HIDDEN,)),
                (f"{p}.input_layernorm.bias", (HIDDEN,)),
                (f"{p}.attention.query_key_value.weight", (3 * HIDDEN, HIDDEN)),
                (f"{p}.attention.dense.weight", (HIDDEN, HIDDEN)),
                (f"{p}.post_attention_layernorm.weight", (HIDDEN,)),
                (f"{p}.post_attention_layernorm.bias", (HIDDEN,)),
                (f"{p}.mlp.dense_h4h.weight", (INTERMEDIATE, HIDDEN)),
                (f"{p}.mlp.dense_4h2.weight", (HIDDEN, INTERMEDIATE)),
            ]
        )
    specs.extend(
        [
            ("model.final_layer_norm.weight", (HIDDEN,)),
            ("model.final_layer_norm.bias", (HIDDEN,)),
            ("model.embed_out.weight", (HIDDEN, VOCAB)),
        ]
    )
    return [
        ParameterInfo(name=name, shape=shape, dtype="float32", numel=_numel(shape))
        for name, shape in specs
    ]


def build_modules() -> list[ModuleInfo]:
    modules: list[ModuleInfo] = [
        ModuleInfo("", "FakeForCausalLM", 0, ("model",)),
        ModuleInfo(
            "model",
            "FakeModel",
            0,
            ("embed_in", "layers", "final_layer_norm", "embed_out"),
        ),
        ModuleInfo("model.embed_in", "Embedding", VOCAB * HIDDEN, ()),
        ModuleInfo(
            "model.layers", "ModuleList", 0, tuple(str(i) for i in range(LAYERS))
        ),
    ]
    for layer in range(LAYERS):
        p = f"model.layers.{layer}"
        modules.extend(
            [
                ModuleInfo(
                    p,
                    "FakeBlock",
                    0,
                    ("input_layernorm", "attention", "post_attention_layernorm", "mlp"),
                ),
                ModuleInfo(f"{p}.input_layernorm", "LayerNorm", 2 * HIDDEN, ()),
                ModuleInfo(f"{p}.attention", "FakeAttention", 0, ("query_key_value", "dense")),
                ModuleInfo(f"{p}.attention.query_key_value", "Linear", 3 * HIDDEN * HIDDEN, ()),
                ModuleInfo(f"{p}.attention.dense", "Linear", HIDDEN * HIDDEN, ()),
                ModuleInfo(f"{p}.post_attention_layernorm", "LayerNorm", 2 * HIDDEN, ()),
                ModuleInfo(f"{p}.mlp", "FakeMLP", 0, ("dense_h4h", "dense_4h2")),
                ModuleInfo(f"{p}.mlp.dense_h4h", "Linear", INTERMEDIATE * HIDDEN, ()),
                ModuleInfo(f"{p}.mlp.dense_4h2", "Linear", HIDDEN * INTERMEDIATE, ()),
            ]
        )
    modules.extend(
        [
            ModuleInfo("model.final_layer_norm", "LayerNorm", 2 * HIDDEN, ()),
            ModuleInfo("model.embed_out", "Linear", HIDDEN * VOCAB, ()),
        ]
    )
    return modules


class FakeLoadedModel:
    """A tiny GPT-NeoX-shaped model implementing the ``LoadedModel`` contract."""

    def __init__(
        self,
        identity: ModelIdentity | None = None,
        config: dict | None = None,
        params: list[ParameterInfo] | None = None,
        modules: list[ModuleInfo] | None = None,
    ) -> None:
        self._identity = identity or ModelIdentity(
            family="fake", name="fake-16m", version="default", source="test:fake"
        )
        self._config = ImmutableMap(config or DEFAULT_CONFIG)
        self._params = params if params is not None else build_params()
        self._modules = modules if modules is not None else build_modules()

    @property
    def identity(self) -> ModelIdentity:
        return self._identity

    @property
    def config(self) -> ImmutableMap:
        return self._config

    def parameters(self) -> Iterator[ParameterInfo]:
        yield from self._params

    def modules(self) -> Iterator[ModuleInfo]:
        yield from self._modules


def make_fake_model() -> FakeLoadedModel:
    return FakeLoadedModel()
