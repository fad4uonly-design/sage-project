"""PyTorch / Hugging Face ``transformers`` adapter for the loading boundary.

This is the ONLY place that imports ``torch``/``transformers``, and it does so
lazily inside :meth:`PyTorchModelLoader.load`, so the research layer and its
unit tests never require those dependencies.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from ..domain.architecture_map import ModuleInfo, ParameterInfo
from ..domain.collections import ImmutableMap
from ..domain.model_artifact import LoadOptions, ModelArtifact, ModelIdentity
from ..interfaces.model_loader import LoadedModel, ModelLoader


@dataclass
class PyTorchLoadedModel:
    """Normalized view over a loaded ``torch.nn.Module``."""

    _model: Any
    identity: ModelIdentity
    config: ImmutableMap

    def parameters(self) -> Iterator[ParameterInfo]:
        for name, param in self._model.named_parameters():
            yield ParameterInfo(
                name=name,
                shape=tuple(param.shape),
                dtype=str(param.dtype),
                numel=int(param.numel()),
                requires_grad=bool(param.requires_grad),
            )

    def modules(self) -> Iterator[ModuleInfo]:
        for name, module in self._model.named_modules():
            direct = sum(int(p.numel()) for p in module.parameters(recurse=False))
            child_names = tuple(child_name for child_name, _ in module.named_children())
            yield ModuleInfo(
                name=name,
                class_name=module.__class__.__name__,
                num_parameters=direct,
                child_names=child_names,
            )


class PyTorchModelLoader(ModelLoader):
    """Loads a Hugging Face ``transformers``/PyTorch checkpoint into the
    normalized :class:`LoadedModel` contract.

    Defaults to CPU and no dtype override (the checkpoint's own dtype) so the
    inspection path is deterministic and cheap. GPU/dtype overrides are
    available via :class:`~sage_research.domain.model_artifact.LoadOptions`.
    """

    def load(self, artifact: ModelArtifact, options: LoadOptions | None = None) -> LoadedModel:
        options = options or LoadOptions()
        try:
            import torch  # noqa: F401
            from transformers import AutoConfig, AutoModelForCausalLM
        except ImportError as exc:  # pragma: no cover - depends on environment
            raise RuntimeError(
                "PyTorchModelLoader requires the 'pytorch' extra: "
                "install with `pip install 'sage-research-system[pytorch]'`"
            ) from exc

        source = _source_ref(artifact)
        revision = options.revision
        dtype = _torch_dtype(options.dtype)

        config = AutoConfig.from_pretrained(source, revision=revision)
        model = AutoModelForCausalLM.from_pretrained(
            source,
            revision=revision,
            config=config,
            torch_dtype=dtype,
            low_cpu_mem_usage=True,
        )
        model.eval()

        device = options.device or "cpu"
        model.to(device)

        return PyTorchLoadedModel(
            _model=model,
            identity=artifact.to_identity(),
            config=ImmutableMap(config.to_dict()),
        )


def _source_ref(artifact: ModelArtifact) -> str:
    src = artifact.source
    if src.startswith("huggingface:"):
        return src[len("huggingface:"):]
    if src.startswith("local:"):
        return src[len("local:"):]
    return src


def _torch_dtype(name: str | None) -> Any:
    if not name:
        return None
    import torch

    mapping = {
        "float16": torch.float16,
        "fp16": torch.float16,
        "bfloat16": torch.bfloat16,
        "bf16": torch.bfloat16,
        "float32": torch.float32,
        "fp32": torch.float32,
        "float64": torch.float64,
    }
    key = name.strip().lower()
    if key not in mapping:
        raise ValueError(f"unsupported dtype {name!r}; expected one of {sorted(mapping)}")
    return mapping[key]
