"""PyTorch adapter for the generative (bench) port.

Like :mod:`~sage_research.infrastructure.pytorch_loader`, this is the ONLY
place that imports ``torch``/``transformers``, and it does so lazily so the
research layer and its unit tests never require those dependencies.

``hf_candidates`` from the registry are tried in order: the first repo that
loads wins. This lets a registry row prefer a newer release (e.g. OLMo 3)
while remaining runnable on a verified fallback.
"""

from __future__ import annotations

from typing import Any

from ..domain.model_artifact import LoadOptions, ModelArtifact, ModelIdentity
from ..interfaces.generative import GenerativeModelLoader


class PyTorchGenerativeHandle:
    """Normalized generate-capability handle over a causal LM."""

    def __init__(self, identity: ModelIdentity, model: Any, tokenizer: Any) -> None:
        self._identity = identity
        self._model = model
        self._tokenizer = tokenizer

    @property
    def identity(self) -> ModelIdentity:
        return self._identity

    def generate(self, prompt: str, *, max_new_tokens: int = 40) -> str:
        import torch

        inputs = self._tokenizer(prompt, return_tensors="pt")
        with torch.no_grad():
            output = self._model.generate(
                **inputs,
                max_new_tokens=max_new_tokens,
                do_sample=False,
                pad_token_id=self._tokenizer.eos_token_id,
            )
        text = self._tokenizer.decode(
            output[0][inputs["input_ids"].shape[1]:],
            skip_special_tokens=True,
        )
        return text.strip()


class PyTorchGenerativeLoader(GenerativeModelLoader):
    """Loads a Hugging Face causal LM into a :class:`GenerativeModelHandle`.

    The artifact source may name one repo, or the caller can pre-resolve a
    candidate list (see ``sage_research.domain.model_registry``) and pass the
    winner via ``options.extra["hf_candidates"]``.
    """

    def load(
        self,
        artifact: ModelArtifact,
        options: LoadOptions | None = None,
    ) -> PyTorchGenerativeHandle:
        options = options or LoadOptions()
        try:
            import torch  # noqa: F401
            from transformers import AutoModelForCausalLM, AutoTokenizer
        except ImportError as exc:  # pragma: no cover - depends on environment
            raise RuntimeError(
                "PyTorchGenerativeLoader requires the 'pytorch' extra: "
                "install with `pip install 'sage-research-system[pytorch]'`"
            ) from exc

        candidates = _candidate_sources(artifact, options)
        last_error: Exception | None = None
        for source in candidates:
            try:
                tokenizer = AutoTokenizer.from_pretrained(
                    source, revision=options.revision
                )
                model = AutoModelForCausalLM.from_pretrained(
                    source,
                    revision=options.revision,
                    low_cpu_mem_usage=True,
                )
                model.eval()
                model.to(options.device or "cpu")
                return PyTorchGenerativeHandle(
                    identity=artifact.to_identity(),
                    model=model,
                    tokenizer=tokenizer,
                )
            except Exception as exc:  # try the next candidate repo
                last_error = exc
        raise RuntimeError(
            f"Could not load any candidate source for {artifact.name!r}: "
            f"{candidates} (last error: {last_error!r})"
        )


def _candidate_sources(artifact: ModelArtifact, options: LoadOptions) -> list[str]:
    """Resolve the list of repo ids to try, in preference order."""
    extra = options.extra.to_dict() if hasattr(options.extra, "to_dict") else {}
    raw_candidates = extra.get("hf_candidates")
    if isinstance(raw_candidates, (list, tuple)) and raw_candidates:
        return [str(item) for item in raw_candidates]

    source = artifact.source
    if source.startswith("huggingface:"):
        source = source[len("huggingface:"):]
    elif source.startswith("local:"):
        source = source[len("local:"):]
    return [source]
