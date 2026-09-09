"""Vision adapter — SmolVLM behind an OpenAI-compatible endpoint.

Phase 4 capability: image understanding behind the :class:`VisionModel`
protocol. Works with Ollama's OpenAI-compatible endpoint (``/v1``) and any
other server that accepts multimodal ``image_url`` content parts.

The concrete model is configured, not hardcoded — ``smolvlm`` is simply the
documented default. Vision is OFF unless ``perception.vision_provider`` is
set, so enabling it is always an explicit user decision.
"""

from __future__ import annotations

from typing import Any

import httpx

from sage.config.settings import Settings
from sage.logging import get_logger
from sage.models.interfaces import ImageInput, VisionModel

log = get_logger(__name__)


class SmolVLMVisionModel:
    """Image understanding via a local multimodal chat endpoint."""

    def __init__(
        self,
        base_url: str,
        model_name: str = "smolvlm",
        timeout: float = 120.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model_name = model_name
        self._timeout = timeout
        self._transport = transport

    @property
    def provider(self) -> str:
        return "local"

    @property
    def model_name(self) -> str:
        return self._model_name

    async def describe(
        self,
        image: ImageInput,
        *,
        question: str | None = None,
    ) -> str:
        prompt = question or "Describe this image concisely."
        payload: dict[str, Any] = {
            "model": self._model_name,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": image.as_data_url()},
                        },
                    ],
                }
            ],
            "temperature": 0.2,
        }

        async with httpx.AsyncClient(
            timeout=self._timeout, transport=self._transport
        ) as client:
            response = await client.post(
                f"{self._base_url}/chat/completions",
                json=payload,
            )
            response.raise_for_status()
            data = response.json()

        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(
                "Unrecognized vision response format."
            ) from exc
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError("Vision endpoint returned no content.")
        return content.strip()


def build_vision_model(settings: Settings) -> VisionModel | None:
    """Settings-driven factory; returns None when vision is not enabled."""
    perception = settings.perception
    if perception.vision_provider.lower() != "local":
        return None
    log.info(
        "perception.vision_enabled",
        model=perception.vision_model_name,
        base_url=perception.vision_base_url,
    )
    return SmolVLMVisionModel(
        base_url=perception.vision_base_url,
        model_name=perception.vision_model_name,
        timeout=perception.vision_timeout,
    )


def _assert_protocol() -> None:
    _: VisionModel = SmolVLMVisionModel(base_url="http://127.0.0.1:11434/v1")
