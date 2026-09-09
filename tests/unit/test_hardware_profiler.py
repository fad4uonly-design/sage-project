"""Unit tests for the hardware profiler — every probe is mocked, so these
tests never depend on actual GPU presence or machine specs."""

from __future__ import annotations

from sage.core import hardware_profiler as hp
from sage.core.hardware_profiler import GpuInfo, HardwareProfile, detect

GIB = 1024.0**3


def test_detect_with_mocked_probes() -> None:
    profile = detect(
        gpu_prober=lambda: GpuInfo(name="NVIDIA GeForce RTX 3080", vram_gb=10.0),
        ram_probe=lambda: 32.0,
        cpu_probe=lambda: 16,
        disk_probe=lambda: 512.5,
    )
    assert profile == HardwareProfile(
        gpu_available=True,
        vram_gb=10.0,
        ram_gb=32.0,
        cpu_cores=16,
        free_disk_gb=512.5,
    )
    assert profile.gpu_available is True
    assert profile.vram_gb == 10.0


def test_detect_without_gpu() -> None:
    profile = detect(
        gpu_prober=lambda: None,
        ram_probe=lambda: 8.0,
        cpu_probe=lambda: 4,
        disk_probe=lambda: 100.0,
    )
    assert profile.gpu_available is False
    assert profile.vram_gb is None
    assert profile.ram_gb == 8.0
    assert profile.cpu_cores == 4
    assert profile.free_disk_gb == 100.0


def test_gpu_present_but_vram_unknown() -> None:
    profile = detect(
        gpu_prober=lambda: GpuInfo(name="Intel Iris Xe", vram_gb=None),
        ram_probe=lambda: 8.0,
        cpu_probe=lambda: 4,
        disk_probe=lambda: 100.0,
    )
    assert profile.gpu_available is True
    assert profile.vram_gb is None


def test_raising_gpu_prober_degrades_to_no_gpu() -> None:
    def boom() -> GpuInfo:
        raise RuntimeError("no GPU tooling")

    profile = detect(
        gpu_prober=boom,
        ram_probe=lambda: 8.0,
        cpu_probe=lambda: 4,
        disk_probe=lambda: 1.0,
    )
    assert profile.gpu_available is False
    assert profile.vram_gb is None


def test_nvidia_smi_parsing_single_gpu() -> None:
    info = hp.parse_nvidia_smi_output("NVIDIA GeForce RTX 3080, 10240\n")
    assert info is not None
    assert info.name == "NVIDIA GeForce RTX 3080"
    assert info.vram_gb == 10.0  # 10240 MiB == 10.0 GiB


def test_nvidia_smi_parsing_multi_gpu_takes_first() -> None:
    info = hp.parse_nvidia_smi_output("NVIDIA A100, 40960\nNVIDIA GTX 1650, 4096\n")
    assert info is not None
    assert info.name == "NVIDIA A100"
    assert info.vram_gb == 40.0


def test_nvidia_smi_unparseable_memory_still_reports_gpu() -> None:
    info = hp.parse_nvidia_smi_output("Weird GPU, N/A\n")
    assert info is not None
    assert info.name == "Weird GPU"
    assert info.vram_gb is None


def test_nvidia_smi_empty_output_is_no_gpu() -> None:
    assert hp.parse_nvidia_smi_output("") is None
    assert hp.parse_nvidia_smi_output("\n   \n") is None


def test_proc_meminfo_parser() -> None:
    text = "MemTotal:       16384000 kB\nMemFree:         102400 kB\n"
    assert hp._ram_from_proc_meminfo(text) == 16384000 * 1024.0 / GIB
    assert hp._ram_from_proc_meminfo("NoMemHere: 1 kB") is None
    assert hp._ram_from_proc_meminfo("MemTotal: not-a-number kB") is None


def test_psutil_ram_probe_with_fake_module() -> None:
    class FakeVM:
        total = 8 * 1024**3

    class FakePsutil:
        def virtual_memory(self) -> FakeVM:
            return FakeVM()

    assert hp._ram_via_psutil(FakePsutil()) == 8.0


def test_psutil_ram_probe_with_broken_module_returns_none() -> None:
    class BrokenPsutil:
        def virtual_memory(self) -> object:
            raise RuntimeError("boom")

    assert hp._ram_via_psutil(BrokenPsutil()) is None


def test_default_gpu_prober_chain_all_missing(monkeypatch) -> None:
    monkeypatch.setattr(hp, "_gpu_via_pynvml", lambda: None)
    monkeypatch.setattr(hp, "_gpu_via_nvidia_smi", lambda: None)
    assert hp.default_gpu_prober() is None


def test_default_gpu_prober_chain_prefers_pynvml(monkeypatch) -> None:
    monkeypatch.setattr(hp, "_gpu_via_pynvml", lambda: GpuInfo(name="NVML GPU", vram_gb=24.0))
    monkeypatch.setattr(hp, "_gpu_via_nvidia_smi", lambda: GpuInfo(name="SMI GPU", vram_gb=8.0))
    info = hp.default_gpu_prober()
    assert info is not None
    assert info.name == "NVML GPU"
    assert info.vram_gb == 24.0


def test_default_probes_return_sane_values_on_this_machine() -> None:
    """Live smoke test: RAM/CPU/disk must exist on any dev machine or CI box.

    GPU assertions are deliberately type-only — CI machines may or may not
    have NVIDIA tooling installed.
    """
    profile = hp.detect()
    assert profile.ram_gb > 0.0
    assert profile.cpu_cores >= 1
    assert profile.free_disk_gb > 0.0
    assert isinstance(profile.gpu_available, bool)
    if profile.gpu_available:
        assert profile.vram_gb is None or profile.vram_gb > 0.0

