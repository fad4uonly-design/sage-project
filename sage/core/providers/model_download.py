"""Real model-download providers — Hugging Face Hub + Ollama — for the model gate.

Implements the ``DownloadFn`` contract defined in ``sage/core/model_gate.py``::

    DownloadFn = Callable[[ModelCard, HardwareProfile], Awaitable[DownloadResult]]

This module executes an ALREADY-APPROVED download. It deliberately does
NOT re-decide anything the model gate already checked (hardware fit,
human approval): it only performs the pull and reports the outcome
(actual size + revision/digest where available) so the gate's audit entry
records it.

Downloader selection: ``DefaultDownloader`` dispatches on
``card.identity.source`` (additive default ``"huggingface"``):

* ``"huggingface"`` -> ``HuggingFaceHubDownloader`` (HF Hub
  ``snapshot_download``, deferred import)
* ``"ollama"``     -> ``OllamaDownloader`` (local REST API + ``ollama`` CLI
  fallback)

Both are **import-guarded**: SAGE imports fine without ``huggingface_hub``
or an ``ollama`` binary; a missing optional dependency only surfaces as a
failing ``DownloadResult`` when a download is actually attempted. Tests
inject fake clients through the constructor seams — real model weights are
never downloaded in the test suite.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sage.logging import get_logger

if TYPE_CHECKING:
    from sage.core.hardware_profiler import HardwareProfile
    from sage.core.model_gate import DownloadFn, DownloadResult
    from sage.models.model_card import ModelCard

log = get_logger(__name__)

MODEL_SOURCE_HF = "huggingface"
MODEL_SOURCE_OLLAMA = "ollama"

OLLAMA_BASE_URL = "http://localhost:11434"
OLLAMA_TAGS_TIMEOUT_S = 3.0
OLLAMA_PULL_TIMEOUT_S = 3600.0
OLLAMA_SHOW_TIMEOUT_S = 10.0


# ---------------------------------------------------------------------------
# Size / checksum helpers (best effort — never block the download on them)
# ---------------------------------------------------------------------------


def _dir_size_gb(path: Path) -> float | None:
    """Total size of regular files under ``path``, ignoring HF cache dirs."""
    total = 0
    for f in path.rglob("*"):
        if f.is_file() and ".cache" not in f.parts and ".git" not in f.parts:
            with contextlib.suppress(OSError):
                total += f.stat().st_size
    return None if total == 0 else total / (1024**3)


def _single_file_sha256(path: Path) -> str | None:
    """sha256 of the ONLY top-level regular file under ``path``, else None.

    A multi-file repo has no single meaningful checksum, so SAGE reports
    ``None`` there rather than inventing an aggregate hash.
    """
    files = [f for f in path.iterdir() if f.is_file() and not f.name.startswith(".")]
    if len(files) != 1:
        return None
    h = hashlib.sha256()
    with files[0].open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _ollama_digest(data: dict[str, Any]) -> str | None:
    digest = data.get("digest")
    return str(digest) if digest else None
# ---------------------------------------------------------------------------
# Hugging Face Hub
# ---------------------------------------------------------------------------


class HuggingFaceHubDownloader:
    """``DownloadFn`` that pulls a HF Hub repo via ``snapshot_download``.

    ``client_factory`` returns the callable used for the pull. It defaults
    to a lazy import of ``huggingface_hub.snapshot_download``; tests inject
    a fake client so no real network/weights are ever touched.
    """

    def __init__(
        self,
        *,
        client_factory: Callable[[], Any] | None = None,
        models_dir: Path | None = None,
    ) -> None:
        self._client_factory = client_factory or self._real_client
        self._models_dir = (
            Path(models_dir)
            if models_dir
            else Path.home() / ".cache" / "sage" / "models"
        )

    def _real_client(self) -> Any:
        # Import-guarded: SAGE loads fine without huggingface_hub installed.
        import huggingface_hub  # noqa: F401  # optional dep, silenced via mypy override

        return huggingface_hub.snapshot_download

    async def _run(self, repo_id: str, local_dir: Path) -> DownloadResult:
        from sage.core.model_gate import DownloadResult  # deferred: avoids import cycle

        try:
            client = self._client_factory()
            self._models_dir.mkdir(parents=True, exist_ok=True)
            client(repo_id=repo_id, local_dir=str(local_dir))
        except Exception as exc:
            return DownloadResult(success=False, error=str(exc))

        size_gb = _dir_size_gb(local_dir)
        if not size_gb:
            return DownloadResult(
                success=False,
                error=f"HF snapshot for {repo_id!r} produced no pullable files",
            )
        return DownloadResult(
            success=True,
            final_size_gb=size_gb,
            checksum=_single_file_sha256(local_dir),
            local_path=str(local_dir),
        )

    async def __call__(self, card: ModelCard, hardware: HardwareProfile) -> DownloadResult:
        target = (
            self._models_dir
            / card.identity.name.replace("/", "__")
            / card.identity.version
        )
        return await self._run(card.identity.name, target)
# ---------------------------------------------------------------------------
# Ollama
# ---------------------------------------------------------------------------


class OllamaDownloader:
    """``DownloadFn`` for a local Ollama registry (HTTP API + CLI fallback).

    The three I/O seams (``http_get``/``http_post``/``cli_pull``) are
    injectable so tests substitute fakes and never touch the network.
    """

    def __init__(
        self,
        *,
        base_url: str = OLLAMA_BASE_URL,
        cli: str = "ollama",
        http_get: Callable[[str, float], tuple[int, dict[str, Any]]] | None = None,
        http_post: Callable[
            [str, dict[str, Any], float], tuple[int, dict[str, Any]]
        ] | None = None,
        cli_pull: Callable[[str], int] | None = None,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._cli = cli
        self._http_get = http_get or self._real_http_get
        self._http_post = http_post or self._real_http_post
        self._cli_pull = cli_pull or self._real_cli_pull

    def _real_http_get(self, path: str, timeout: float) -> tuple[int, dict[str, Any]]:
        import requests

        resp = requests.get(f"{self._base}{path}", timeout=timeout)
        try:
            return resp.status_code, resp.json()
        except ValueError:
            return resp.status_code, {}

    def _real_http_post(
        self,
        path: str,
        payload: dict[str, Any],
        timeout: float,
    ) -> tuple[int, dict[str, Any]]:
        import requests

        resp = requests.post(f"{self._base}{path}", json=payload, timeout=timeout)
        try:
            return resp.status_code, resp.json()
        except ValueError:
            return resp.status_code, {}

    def _real_cli_pull(self, model: str) -> int:
        import subprocess

        proc = subprocess.run(
            [self._cli, "pull", model],
            capture_output=True,
            text=True,
            timeout=OLLAMA_PULL_TIMEOUT_S,
        )
        return proc.returncode

    async def __call__(self, card: ModelCard, hardware: HardwareProfile) -> DownloadResult:
        from sage.core.model_gate import DownloadResult  # deferred: avoids import cycle

        model = card.identity.name

        # 1. Is Ollama reachable, and do we already have the model?
        tags_status, tags_data = 0, {}
        with contextlib.suppress(Exception):
            # API down — try the CLI fallback below.
            result = await asyncio.to_thread(
                self._http_get, "/api/tags", OLLAMA_TAGS_TIMEOUT_S
            )
            if result is not None:
                tags_status, tags_data = (
                    result[0],
                    result[1] if isinstance(result[1], dict) else {},
                )

        if tags_status == 200:
            existing = [
                m.get("name") if isinstance(m, dict) else str(m)
                for m in tags_data.get("models", [])
            ]
            if any(m == model for m in existing):
                return DownloadResult(success=True, local_path=f"{self._base}/{model}")

            # 2. Pull (non-streaming), then ask Ollama for the digest/size.
            status, data = await asyncio.to_thread(
                self._http_post,
                "/api/pull",
                {"name": model, "stream": False},
                OLLAMA_PULL_TIMEOUT_S,
            )
            if status == 200:
                return DownloadResult(
                    success=True,
                    checksum=_ollama_digest(data),
                    final_size_gb=await self._show_size_gb(model),
                    local_path=f"{self._base}/{model}",
                )
            if status == 404:
                return DownloadResult(
                    success=False, error=f"Ollama: model not found: {model!r}"
                )
            return DownloadResult(
                success=False, error=f"Ollama pull failed (HTTP {status})"
            )

        # 3. API unreachable -> CLI fallback (report *its* failure honestly).
        try:
            rc = await asyncio.to_thread(self._cli_pull, model)
        except Exception as exc:
            return DownloadResult(
                success=False,
                error=f"Ollama API unreachable and `ollama pull` failed: {exc}",
            )
        if rc == 0:
            return DownloadResult(success=True, local_path=f"{self._base}/{model}")
        return DownloadResult(
            success=False, error=f"`ollama pull {model}` exited with code {rc}"
        )

    async def _show_size_gb(self, model: str) -> float | None:
        """Best-effort actual disk size from ``/api/show``; None if unknown."""
        try:
            status, data = await asyncio.to_thread(
                self._http_post, "/api/show", {"name": model}, OLLAMA_SHOW_TIMEOUT_S
            )
        except Exception:
            return None
        if status != 200 or not isinstance(data, dict) or not data.get("size"):
            return None
        try:
            return float(data["size"]) / (1024**3)
        except (TypeError, ValueError):
            return None


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


class DefaultDownloader:
    """``DownloadFn`` that dispatches on ``card.identity.source`` and always
    returns a ``DownloadResult`` — the gate audits failures instead of
    crashing on them.
    """

    def __init__(
        self,
        *,
        hf_factory: Callable[[], Any] | None = None,
        models_dir: Path | None = None,
        ollama: OllamaDownloader | None = None,
    ) -> None:
        self._models_dir = models_dir
        self._hf: HuggingFaceHubDownloader | None = (
            HuggingFaceHubDownloader(client_factory=hf_factory, models_dir=models_dir)
            if hf_factory
            else None
        )
        self._ollama = ollama or OllamaDownloader()

    async def __call__(self, card: ModelCard, hardware: HardwareProfile) -> DownloadResult:
        if card.identity.source == MODEL_SOURCE_OLLAMA:
            return await self._ollama(card, hardware)
        if self._hf is None:
            self._hf = HuggingFaceHubDownloader(models_dir=self._models_dir)
        return await self._hf(card, hardware)


#: Module-level default the model gate wires into its construction site.
default_downloader: DownloadFn = DefaultDownloader()
