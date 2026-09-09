"""Hardware Profiler — detect what machine SAGE is running on.

Phase 1 of the hardware-aware roadmap: this module only *profiles* the
machine (GPU/VRAM presence, RAM, CPU cores, free disk). Later phases (model
download gating, placement decisions) are separate modules that will consume
``HardwareProfile``; nothing here gates or downloads anything.

Cross-platform, Windows-first (SAGE runs on D:\\sage on Windows):

- RAM/CPU/disk: uses ``psutil`` when importable, with pure-stdlib fallbacks
  (ctypes ``GlobalMemoryStatusEx`` on Windows, ``/proc/meminfo`` on Linux,
  ``os.cpu_count``, ``shutil.disk_usage``) so the module works with zero
  third-party dependencies. Install ``psutil`` for richer/normalized values;
  it is picked up automatically, no code changes needed.
- GPU: tries ``pynvml`` (in-process, preferred), then parses ``nvidia-smi``
  output (covered by NVIDIA driver installs on Windows), then falls back to
  ``gpu_available=False``. Only NVIDIA is probed; AMD/Intel GPUs simply
  report as unavailable for now.

Everything is injectable: ``detect()`` accepts probe callables so tests can
mock the machine instead of depending on actual hardware. The default
probes never raise — they degrade to conservative values (``0.0`` /
``gpu_available=False``) when a source is unavailable.
"""

from __future__ import annotations

import contextlib
import ctypes
import importlib.util
import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sage.logging import get_logger

log = get_logger(__name__)

_GIB = 1024.0**3
_SMI_TIMEOUT_SECONDS = 5.0


@dataclass(frozen=True)
class GpuInfo:
    """What the GPU probers found (``None`` vram_gb => present but unknown)."""

    name: str | None
    vram_gb: float | None


@dataclass(frozen=True)
class HardwareProfile:
    """Snapshot of the machine's compute resources (gigabyte units = GiB)."""

    gpu_available: bool
    vram_gb: float | None
    ram_gb: float
    cpu_cores: int
    free_disk_gb: float


# -- RAM probes ---------------------------------------------------------------


def _load_optional_module(name: str) -> Any | None:
    """Import an optional dependency if present; never raise."""
    try:
        if importlib.util.find_spec(name) is None:
            return None
        return importlib.import_module(name)
    except Exception:
        return None


def _ram_via_psutil(psutil_mod: Any) -> float | None:
    try:
        total = psutil_mod.virtual_memory().total
        return float(total) / _GIB
    except Exception:
        return None


def _ram_via_win32() -> float | None:
    """Total physical RAM via kernel32 GlobalMemoryStatusEx (Windows only)."""
    if sys.platform != "win32":
        return None
    windll = getattr(ctypes, "windll", None)
    if windll is None:
        return None

    class _MemoryStatusEx(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    try:
        stat = _MemoryStatusEx()
        stat.dwLength = ctypes.sizeof(_MemoryStatusEx)
        if not windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
            return None
        return float(stat.ullTotalPhys) / _GIB
    except Exception:
        return None


def _ram_from_proc_meminfo(meminfo_text: str) -> float | None:
    """Parse ``/proc/meminfo`` (Linux) — pure function, trivially testable."""
    for line in meminfo_text.splitlines():
        if line.startswith("MemTotal:"):
            parts = line.split()
            if len(parts) >= 2:
                try:
                    return float(parts[1]) * 1024.0 / _GIB  # kB -> bytes -> GiB
                except ValueError:
                    return None
    return None


def _ram_via_proc() -> float | None:
    if sys.platform == "win32":
        return None
    try:
        with open("/proc/meminfo", encoding="ascii") as handle:
            return _ram_from_proc_meminfo(handle.read())
    except OSError:
        return None


def default_ram_probe() -> float:
    """Total RAM in GiB: psutil -> win32 -> /proc/meminfo -> 0.0."""
    psutil_mod = _load_optional_module("psutil")
    if psutil_mod is not None:
        value = _ram_via_psutil(psutil_mod)
        if value is not None:
            return value
    for fallback in (_ram_via_win32, _ram_via_proc):
        value = fallback()
        if value is not None:
            return value
    log.warning("hardware.ram_probe_unavailable")
    return 0.0


# -- CPU / disk probes --------------------------------------------------------


def default_cpu_probe() -> int:
    """Logical CPU core count (psutil if present, else os.cpu_count)."""
    psutil_mod = _load_optional_module("psutil")
    if psutil_mod is not None:
        try:
            count = psutil_mod.cpu_count(logical=True)
            if count:
                return int(count)
        except Exception:
            pass
    return os.cpu_count() or 1


def default_disk_probe(disk_path: str | None = None) -> Callable[[], float]:
    """Return a zero-arg probe for free disk space (GiB) on ``disk_path``.

    Defaults to the current working directory's drive — pass the SAGE data
    directory to profile the drive SAGE actually writes to.
    """

    def probe() -> float:
        target = disk_path or os.getcwd()
        try:
            return shutil.disk_usage(target).free / _GIB
        except OSError:
            log.warning("hardware.disk_probe_unavailable", path=target)
            return 0.0

    return probe


# -- GPU probes ---------------------------------------------------------------


def _gpu_via_pynvml() -> GpuInfo | None:
    """GPU info via the pynvml/NVIDIA Management Library, if installed."""
    pynvml = _load_optional_module("pynvml")
    if pynvml is None:
        return None
    try:
        pynvml.nvmlInit()
        handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        memory = pynvml.nvmlDeviceGetMemoryInfo(handle)
        raw_name = pynvml.nvmlDeviceGetName(handle)
        name = raw_name.decode() if isinstance(raw_name, bytes) else str(raw_name)
        return GpuInfo(name=name or None, vram_gb=float(memory.total) / _GIB)
    except Exception:
        return None
    finally:
        with contextlib.suppress(Exception):
            pynvml.nvmlShutdown()


def parse_nvidia_smi_output(output: str) -> GpuInfo | None:
    """Parse ``nvidia-smi --query-gpu=name,memory.total --format=csv,noheader``.

    Pure function. Memory comes back in MiB (``nounits``); the first GPU line
    wins (multi-GPU profiling can come later). Unparseable memory yields a
    present GPU with unknown VRAM; empty output yields ``None``.
    """
    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        name: str | None = None
        vram_gb: float | None = None
        if "," in line:
            raw_name, _, raw_memory = line.partition(",")
            name = raw_name.strip() or None
            raw_memory = raw_memory.strip().rstrip("MiB").strip()
            try:
                vram_gb = float(raw_memory) / 1024.0  # MiB -> GiB
            except ValueError:
                vram_gb = None
        else:
            name = line or None
        return GpuInfo(name=name, vram_gb=vram_gb)
    return None


def _gpu_via_nvidia_smi() -> GpuInfo | None:
    """GPU info by shelling out to nvidia-smi (ships with NVIDIA drivers)."""
    smi = shutil.which("nvidia-smi")
    if smi is None:
        return None
    try:
        completed = subprocess.run(
            [smi, "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=_SMI_TIMEOUT_SECONDS,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return parse_nvidia_smi_output(completed.stdout)


def default_gpu_prober() -> GpuInfo | None:
    """First GPU found via pynvml, then nvidia-smi; None if no tooling."""
    return _gpu_via_pynvml() or _gpu_via_nvidia_smi()


# -- detect -------------------------------------------------------------------


def detect(
    *,
    disk_path: str | None = None,
    gpu_prober: Callable[[], GpuInfo | None] | None = None,
    ram_probe: Callable[[], float] | None = None,
    cpu_probe: Callable[[], int] | None = None,
    disk_probe: Callable[[], float] | None = None,
) -> HardwareProfile:
    """Profile this machine. Inject probes to mock hardware in tests.

    Args:
        disk_path: drive/directory whose free space matters (default: the
            current working directory's drive). Ignored when ``disk_probe``
            is injected.
        gpu_prober: returns ``GpuInfo`` or ``None`` when no GPU is found.
        ram_probe: total RAM in GiB.
        cpu_probe: logical core count.
        disk_probe: free disk space in GiB.
    """
    gpu: GpuInfo | None = None
    try:
        gpu = (gpu_prober or default_gpu_prober)()
    except Exception:
        log.warning("hardware.gpu_prober_failed")
        gpu = None

    ram = (ram_probe or default_ram_probe)()
    cores = (cpu_probe or default_cpu_probe)()
    free_disk = (disk_probe or default_disk_probe(disk_path))()

    profile = HardwareProfile(
        gpu_available=gpu is not None,
        vram_gb=gpu.vram_gb if gpu is not None else None,
        ram_gb=ram,
        cpu_cores=cores,
        free_disk_gb=free_disk,
    )
    log.debug(
        "hardware.profile_detected",
        gpu_available=profile.gpu_available,
        vram_gb=profile.vram_gb,
        ram_gb=profile.ram_gb,
        cpu_cores=profile.cpu_cores,
        free_disk_gb=profile.free_disk_gb,
    )
    return profile
