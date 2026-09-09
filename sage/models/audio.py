"""Audio adapter — Whisper Tiny behind an OpenAI-compatible endpoint.

Phase 4 capability: speech input behind the :class:`AudioTranscriber`
protocol. Works with any server exposing ``POST /audio/transcriptions``
(whisper.cpp server, faster-whisper-server, Groq-compatible endpoints).

Speech is OFF unless ``perception.speech_provider`` is set, so enabling it is
always an explicit user decision.
"""

from __future__ import annotations

import httpx

from sage.config.settings import Settings
from sage.logging import get_logger
from sage.models.interfaces import AudioTranscriber

log = get_logger(__name__)


class WhisperTranscriber:
    """Speech-to-text via a local Whisper-compatible endpoint."""

    def __init__(
        self,
        base_url: str,
        model_name: str = "whisper",
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

    async def transcribe(
        self,
        audio: bytes,
        *,
        filename: str = "audio.wav",
        language: str | None = None,
    ) -> str:
        if not audio:
            raise ValueError("audio bytes are required")

        data: dict[str, str] = {"model": self._model_name}
        if language:
            data["language"] = language

        async with httpx.AsyncClient(
            timeout=self._timeout, transport=self._transport
        ) as client:
            response = await client.post(
                f"{self._base_url}/audio/transcriptions",
                data=data,
                files={"file": (filename, audio)},
            )
            response.raise_for_status()
            payload = response.json()

        text = payload.get("text") if isinstance(payload, dict) else None
        if not isinstance(text, str):
            raise RuntimeError("Unrecognized transcription response format.")
        return text.strip()


def build_transcriber(settings: Settings) -> AudioTranscriber | None:
    """Settings-driven factory; returns None when speech is not enabled."""
    perception = settings.perception
    if perception.speech_provider.lower() != "local":
        return None
    log.info(
        "perception.speech_enabled",
        model=perception.speech_model_name,
        base_url=perception.speech_base_url,
    )
    return WhisperTranscriber(
        base_url=perception.speech_base_url,
        model_name=perception.speech_model_name,
        timeout=perception.speech_timeout,
    )


def _assert_protocol() -> None:
    _: AudioTranscriber = WhisperTranscriber(base_url="http://127.0.0.1:8080")
