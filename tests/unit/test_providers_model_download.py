"""Tests for the HuggingFace + Ollama download providers.

No real network or model weights anywhere: every I/O seam (HF
``snapshot_download`` client, Ollama ``http_get``/``http_post``/``cli_pull``)
is injected with fakes.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sage.core.hardware_profiler import HardwareProfile
from sage.core.providers.model_download import (
    DefaultDownloader,
    HuggingFaceHubDownloader,
    OllamaDownloader,
    _dir_size_gb,
    _single_file_sha256,
)
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

HW = HardwareProfile(
    gpu_available=False,
    vram_gb=None,
    ram_gb=16.0,
    cpu_cores=8,
    free_disk_gb=50.0,
)


def make_card(source: str = "huggingface", name: str = "org/mdl") -> ModelCard:
    return ModelCard(
        identity=Identity(name=name, provider="local", version="latest", source=source),
        architecture=Architecture(family="family", param_count_b=1.0),
        capabilities=Capabilities(),
        reasoning=ReasoningLevel.NONE,
        tool_use=ToolUseSupport.NONE,
        context_window_tokens=1000,
        memory_requirements=MemoryRequirements(min_vram_gb=None, min_ram_gb=None),
        quantization_supported=[],
        runtime_compatibility=[RuntimeTarget.TRANSFORMERS],
        api_interface="",
        license="mit",
        strengths=[],
        weaknesses=[],
        cost=Cost(),
        reliability=Reliability(),
    )


def test_identity_source_defaults_to_huggingface() -> None:
    assert Identity(name="x", provider="p").source == "huggingface"


async def test_hf_download_success_reports_size_and_checksum(tmp_path: Path) -> None:
    # Fake client writes one file into the target dir.
    def fake_client(repo_id: str, local_dir: str) -> None:
        p = Path(local_dir)
        p.mkdir(parents=True, exist_ok=True)
        (p / "model.bin").write_bytes(b"x" * 1024)

    dl = HuggingFaceHubDownloader(client_factory=lambda: fake_client, models_dir=tmp_path)
    out = await dl(make_card(), HW)

    assert out.success is True
    assert out.error is None
    assert out.local_path is not None
    assert out.final_size_gb is not None and abs(out.final_size_gb - (1024 / 1024**3)) < 1e-9
    assert isinstance(out.checksum, str) and len(out.checksum) == 64
    assert Path(out.local_path).is_dir()


async def test_hf_client_exception_fails_gracefully(tmp_path: Path) -> None:
    def boom(repo_id: str, local_dir: str) -> None:
        raise RuntimeError("boom")

    dl = HuggingFaceHubDownloader(client_factory=lambda: boom, models_dir=tmp_path)
    out = await dl(make_card(), HW)
    assert out.success is False
    assert "boom" in (out.error or "")


async def test_hf_empty_target_fails(tmp_path: Path) -> None:
    def noop(repo_id: str, local_dir: str) -> None:
        Path(local_dir).mkdir(parents=True, exist_ok=True)

    dl = HuggingFaceHubDownloader(client_factory=lambda: noop, models_dir=tmp_path)
    out = await dl(make_card(), HW)
    assert out.success is False
    assert "no pullable files" in (out.error or "")


async def test_ollama_pull_success_reports_digest(tmp_path: Path) -> None:
    calls: list[str] = []

    def get(path: str, timeout: float) -> tuple[int, dict[str, object]]:
        calls.append(path)
        return 200, {"models": []}

    def post(path: str, payload: dict[str, object], timeout: float) -> tuple[int, dict[str, object]]:
        calls.append(path)
        if path == "/api/pull":
            return 200, {"digest": "sha256:abc123"}
        if path == "/api/show":
            return 200, {"size": 1073741824}  # 1 GiB
        return 404, {}

    dl = OllamaDownloader(base_url="http://localhost:11434", http_get=get, http_post=post)
    out = await dl(make_card(source="ollama"), HW)
    assert out.success is True
    assert out.checksum == "sha256:abc123"
    assert out.final_size_gb == pytest.approx(1.0)
    assert "/api/pull" in calls and "/api/show" in calls


async def test_ollama_pull_404_reports_not_found(tmp_path: Path) -> None:
    def get(path: str, timeout: float) -> tuple[int, dict[str, object]]:
        return 200, {"models": []}

    def post(path: str, payload: dict[str, object], timeout: float) -> tuple[int, dict[str, object]]:
        return 404, {}

    dl = OllamaDownloader(http_get=get, http_post=post)
    out = await dl(make_card(source="ollama", name="nope"), HW)
    assert out.success is False
    assert "not found" in (out.error or "")


async def test_ollama_api_down_falls_back_to_cli(tmp_path: Path) -> None:
    def get(path: str, timeout: float) -> tuple[int, dict[str, object]]:
        raise RuntimeError("connection refused")

    def cli_pull(model: str) -> int:
        return 0

    dl = OllamaDownloader(base_url="http://localhost:11434", http_get=get, cli_pull=cli_pull)
    out = await dl(make_card(source="ollama", name="m"), HW)
    assert out.success is True
    assert out.local_path == "http://localhost:11434/m"


async def test_default_downloader_dispatches_ollama(tmp_path: Path) -> None:
    def get(path: str, timeout: float) -> tuple[int, dict[str, object]]:
        return 200, {"models": []}

    def post(path: str, payload: dict[str, object], timeout: float) -> tuple[int, dict[str, object]]:
        if path == "/api/pull":
            return 200, {}
        return 404, {}

    dl = DefaultDownloader(
        models_dir=tmp_path,
        ollama=OllamaDownloader(base_url="http://x:1", http_get=get, http_post=post),
    )
    out = await dl(make_card(source="ollama", name="m"), HW)
    assert out.success is True


def test_dir_size_gb_and_single_sha256(tmp_path: Path) -> None:
    (tmp_path / "a.bin").write_bytes(b"z" * 2048)
    size_gb = _dir_size_gb(tmp_path)
    assert size_gb is not None and size_gb > 0
    h = _single_file_sha256(tmp_path)
    assert h is not None and len(h) == 64
    (tmp_path / "b.bin").write_bytes(b"y" * 512)
    assert _single_file_sha256(tmp_path) is None  # multi-file -> no single hash


async def test_ollama_existing_model_shortcuts(tmp_path: Path) -> None:
    def fake_get(path: str, timeout: float) -> tuple[int, dict[str, object]]:
        assert path == "/api/tags"
        return 200, {"models": [{"name": "org/mdl"}]}

    dl = OllamaDownloader(base_url="http://x:1", http_get=fake_get)
    out = await dl(make_card(source="ollama"), HW)
    assert out.success is True
    assert out.local_path == "http://x:1/org/mdl"
