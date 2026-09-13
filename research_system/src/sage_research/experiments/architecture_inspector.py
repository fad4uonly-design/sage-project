"""Architecture inspection: normalized model -> ArchitectureMap.

The heuristic classifier here is application logic (not core domain structure):
it maps generic module/parameter naming conventions onto the architecture-neutral
:class:`ComponentKind` vocabulary. It is intentionally conservative and records
its inferences as clearly-labeled structural notes, never causal claims.
"""

from __future__ import annotations

import ast

from ..domain.architecture_map import (
    ArchitectureMap,
    Component,
    ComponentKind,
    Connection,
    ConnectionKind,
    ModelSummary,
)
from ..domain.collections import ImmutableMap
from ..domain.knowledge import utcnow_iso
from ..interfaces.inspector import ArchitectureInspector
from ..interfaces.model_loader import LoadedModel
from ..version import __version__

# Container classes that never count as residual "blocks".
_CONTAINER_CLASSES = {"modulelist", "sequential", "moduledict", "parameterlist"}


class HeuristicArchitectureInspector(ArchitectureInspector):
    """Builds an ArchitectureMap by walking the normalized module tree.

    Classification order (class name first, then dotted name):

    1. normalization  (``LayerNorm``/``RMSNorm``/``BatchNorm``, or ``*norm``)
    2. embedding      (``Embedding``, or ``embed``/``wte``/``tok_embeddings``)
    3. output head    (``*LMHead``, ``embed_out``, ``lm_head``)
    4. attention      (``*Attention*``, or ``attention``/``attn``/``qkv``)
    5. feedforward    (``*MLP*``, or ``mlp``/``ffn``/``feed_forward``/``dense_4h``)
    """

    def inspect(self, model: LoadedModel, *, timestamp_utc: str | None = None) -> ArchitectureMap:
        modules = list(model.modules())
        params = list(model.parameters())
        created = timestamp_utc or utcnow_iso()

        order: dict[str, int] = {m.name: i for i, m in enumerate(modules)}

        # Parameter ownership: a parameter belongs to the module named by its
        # dotted-name prefix.
        param_by_owner: dict[str, list] = {}
        for p in params:
            owner = p.name.rsplit(".", 1)[0] if "." in p.name else ""
            param_by_owner.setdefault(owner, []).append(p)

        leaf_names = [m.name for m in modules if m.num_parameters > 0]
        kind_of: dict[str, ComponentKind] = {
            m.name: _classify(m.name, m.class_name)
            for m in modules
            if m.num_parameters > 0
        }

        # Residual block detection: a zero-direct-parameter module whose
        # descendants contain both attention and feedforward leaves, that is not
        # a pure container class and has no other block as a strict descendant.
        candidates: list[str] = []
        for m in modules:
            if m.num_parameters > 0 or m.name == "":
                continue
            if m.class_name.lower() in _CONTAINER_CLASSES:
                continue
            prefix = m.name + "."
            descendant_kinds = {kind_of[n] for n in leaf_names if n.startswith(prefix)}
            if (
                ComponentKind.ATTENTION in descendant_kinds
                and ComponentKind.FEEDFORWARD in descendant_kinds
            ):
                candidates.append(m.name)

        block_names = [
            c for c in candidates
            if not any(other != c and other.startswith(c + ".") for other in candidates)
        ]

        component_names = sorted(leaf_names + block_names)
        name_to_id = {n: f"cmp-{i:04d}" for i, n in enumerate(component_names)}

        components: list[Component] = []
        for n in component_names:
            m = next(mm for mm in modules if mm.name == n)
            kind = kind_of.get(n) or ComponentKind.BLOCK
            components.append(
                Component(
                    component_id=name_to_id[n],
                    name=n,
                    kind=kind,
                    module_class=m.class_name,
                    parameters=tuple(param_by_owner.get(n, ())),
                    attributes=ImmutableMap({"registration_order": str(order[n])}),
                )
            )

        connections = _build_connections(name_to_id, kind_of, leaf_names, order, components)
        summary = _build_summary(model, modules, params, components, block_names)

        return ArchitectureMap(
            model_identity=model.identity,
            summary=summary,
            components=tuple(components),
            connections=tuple(connections),
            created_utc=created,
            generated_by=f"sage-research-system {__version__}",
        )


def _classify(name: str, class_name: str) -> ComponentKind:
    c = class_name.lower()
    n = name.lower()

    if "layernorm" in c or "rmsnorm" in c or "batchnorm" in c:
        return ComponentKind.NORMALIZATION
    if "embedding" in c:
        return ComponentKind.EMBEDDING
    if "lmhead" in c:
        return ComponentKind.OUTPUT_HEAD
    if "attention" in c or "selfattn" in c:
        return ComponentKind.ATTENTION
    if "mlp" in c:
        return ComponentKind.FEEDFORWARD

    # Name-based fallbacks (dotted module path).
    if "embed_out" in n or "lm_head" in n:
        return ComponentKind.OUTPUT_HEAD
    if "embed" in n or "wte" in n or "tok_embeddings" in n:
        return ComponentKind.EMBEDDING
    if "layernorm" in n or "rmsnorm" in n or "final_norm" in n or n.endswith("norm"):
        return ComponentKind.NORMALIZATION
    if (
        "attention" in n
        or "attn" in n
        or "self_attn" in n
        or "query_key_value" in n
        or "qkv" in n
    ):
        return ComponentKind.ATTENTION
    if (
        "mlp" in n
        or "ffn" in n
        or "feed_forward" in n
        or "dense_4h" in n
        or "dense_h4h" in n
    ):
        return ComponentKind.FEEDFORWARD
    return ComponentKind.OTHER


def _build_connections(
    name_to_id: dict[str, str],
    kind_of: dict[str, ComponentKind],
    leaf_names: list[str],
    order: dict[str, int],
    components: list[Component],
) -> list[Connection]:
    connections: list[Connection] = []

    def cid(n: str) -> str:
        return name_to_id[n]

    embeds = sorted(
        (n for n in leaf_names if kind_of.get(n) == ComponentKind.EMBEDDING),
        key=lambda n: order[n],
    )
    heads = sorted(
        (n for n in leaf_names if kind_of.get(n) == ComponentKind.OUTPUT_HEAD),
        key=lambda n: order[n],
    )
    blocks = sorted(
        (c.name for c in components if c.kind == ComponentKind.BLOCK),
        key=lambda n: order[n],
    )

    # Forward chain: embedding(s) -> blocks -> head(s), in registration order.
    chain = embeds + blocks + heads
    for a, b in zip(chain, chain[1:], strict=False):
        connections.append(
            Connection(cid(a), cid(b), ConnectionKind.FEEDS_INTO, "forward chain (registration order)")
        )

    # Intra-block chains (structural adjacency only, in registration order).
    for b in blocks:
        prefix = b + "."
        leaves = sorted((n for n in leaf_names if n.startswith(prefix)), key=lambda n: order[n])
        for a, b2 in zip(leaves, leaves[1:], strict=False):
            connections.append(
                Connection(cid(a), cid(b2), ConnectionKind.FEEDS_INTO, "intra-block registration order")
            )

    return connections


def _build_summary(model, modules, params, components, block_names) -> ModelSummary:
    cfg = model.config
    total = sum(p.numel for p in params)
    trainable = sum(p.numel for p in params if p.requires_grad)

    label = _cfg_str(cfg, "model_type") or _cfg_str(cfg, "architectures")

    hidden = _cfg_int(cfg, "hidden_size")
    vocab = _cfg_int(cfg, "vocab_size")
    layers = _cfg_int(cfg, "num_hidden_layers") or len(block_names)
    heads = _cfg_int(cfg, "num_attention_heads")
    head_dim = _cfg_int(cfg, "head_dim")
    intermediate = _cfg_int(cfg, "intermediate_size")
    eps = _cfg_float(cfg, "layer_norm_eps")

    # Weight-shape fallbacks.
    embeds = [c for c in components if c.kind == ComponentKind.EMBEDDING]
    if (vocab is None or hidden is None) and embeds and embeds[0].parameters:
        shape = embeds[0].parameters[0].shape
        if len(shape) == 2:
            vocab = vocab if vocab is not None else shape[0]
            hidden = hidden if hidden is not None else shape[1]
    if head_dim is None and heads and hidden and hidden % heads == 0:
        head_dim = hidden // heads

    return ModelSummary(
        total_parameters=total,
        trainable_parameters=trainable,
        num_modules=len(modules),
        architecture_label=label,
        hidden_size=hidden,
        num_layers=layers,
        vocab_size=vocab,
        num_attention_heads=heads,
        head_dim=head_dim,
        intermediate_size=intermediate,
        layer_norm_epsilon=eps,
    )


def _cfg_str(cfg: ImmutableMap, key: str) -> str | None:
    v = cfg.get(key)
    if v is None or v in ("null", "None", ""):
        return None
    if v.startswith("[") and v.endswith("]"):
        try:
            parsed = ast.literal_eval(v)
            if isinstance(parsed, list) and parsed:
                return str(parsed[0])
        except (ValueError, SyntaxError):
            pass
    return v


def _cfg_int(cfg: ImmutableMap, key: str) -> int | None:
    v = cfg.get(key)
    if v is None or v in ("null", "None", ""):
        return None
    try:
        return int(float(v))
    except (ValueError, TypeError):
        return None


def _cfg_float(cfg: ImmutableMap, key: str) -> float | None:
    v = cfg.get(key)
    if v is None or v in ("null", "None", ""):
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None
