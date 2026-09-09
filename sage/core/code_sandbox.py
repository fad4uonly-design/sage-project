"""Code sandbox — isolated subprocess execution for auto-generated code.

Phase 4 safety boundary of the autonomy roadmap. Generated code from the
auto-coder NEVER runs inside the SAGE process: :meth:`CodeSandbox.run` writes
the program and its tests into a private temp working directory, launches a
*fresh* ``python -I -S`` subprocess to execute them there, and only ever
returns a structured :class:`SandboxResult`. Nothing here executes in-process
via ``exec``/``eval``.

Isolation posture
-----------------
* **Separate process** — the child is a new interpreter run with ``-I -S``
  (isolated mode: ignores user env, no user site-packages, no third-party
  imports); the generated code never runs in SAGE's process or address space.
* **No SAGE state** — the child inherits a stripped environment (no SAGE
  secrets, DB paths, or data dir), and its working directory is only its own
  temp sandbox dir.
* **No network (interpreted level)** — the sandbox wrapper patches Python's
  socket / ``http.client`` / ``urllib`` entry points *before* the generated
  code runs, and forbids process spawning (subprocess/os.spawn), which is the
  main escape hatch for outbound connections.
* **Confined filesystem (interpreted level)** — the wrapper intercepts
  ``open``/``io.open``/``os.open`` and all filesystem mutators so generated
  code may only read/write inside its own sandbox dir (stdlib paths remain
  readable so imports keep working).
* **Hard timeout** — the parent kills the child after ``timeout_seconds`` and
  reports ``passed=False`` ("timed out").
* **Resource limit** — POSIX: ``RLIMIT_AS`` set in the child via
  ``preexec_fn``. Windows: a Job-Object hard memory cap via ctypes, best
  effort (see :func:`_apply_windows_job_memory`).

**Windows limitation — read before trusting this too far**
Windows provides no OS-level network-namespace or chroot primitive for an
ordinary user process. The network / filesystem / subprocess blocks above are
interpreted-level guards installed *inside* the child before generated code
executes; they hold against ordinary Python, but a deliberately hostile
program could in principle escape through native calls (e.g. ``ctypes`` into
``ws2_32``/``kernel32``). On this platform the sandbox is therefore a *strong*
boundary, not a *provable* one: it reliably stops accidental / naive access,
contains crashes, and respects the hard timeout, but a hard guarantee requires
a container/VM sandbox. Treat sandbox output as untrusted data regardless.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from sage.logging import get_logger

log = get_logger(__name__)

#: Stdlib transport constants reused by the async subprocess launch.
from asyncio.subprocess import DEVNULL, PIPE  # noqa: E402


@dataclass(frozen=True)
class SandboxResult:
    """Outcome of one sandboxed run. ``passed=False`` is a *normal* result
    (failed test, timeout, blocked access) — never an exception."""

    passed: bool
    output: str = ""
    error: str | None = None
    duration_seconds: float = 0.0


def _sandbox_env(root: Path) -> dict[str, str]:
    """Minimal child environment — no SAGE state, no user profile, no secrets.

    Only what the interpreter needs to boot on this OS is carried over.
    Nothing is inherited from the parent's environment.
    """
    base = os.environ.get("SystemRoot") or os.environ.get("SYSTEMROOT") or ""
    env: dict[str, str] = {}
    if base:
        env["SystemRoot"] = base
        env["SYSTEMROOT"] = base
        env["WINDIR"] = os.environ.get("WINDIR", base)
        env["PATH"] = f"{base}\\System32{os.pathsep}{base}"
    env["COMSPEC"] = os.environ.get("COMSPEC", r"C:\Windows\System32\cmd.exe")
    # Scratch lifespan: the sandbox dir itself.
    env["TEMP"] = str(root)
    env["TMP"] = str(root)
    return env


def _decode(raw: bytes | None) -> str:
    return (raw or b"").decode("utf-8", errors="replace")


def _apply_posix_memory_preexec(memory_mb: int) -> None:
    """Child-side RLIMIT_AS for POSIX (runs in the forked child)."""
    import resource

    limit = int(memory_mb) * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_AS, (limit, limit))


def _apply_windows_job_memory(pid: int, memory_mb: int) -> bool:
    """Best-effort Windows hard memory cap via a Job Object.

    Windows has no ``setrlimit``, so this uses ``JOB_OBJECT_LIMIT_PROCESS_MEMORY``
    through ctypes. It is deliberately *best effort*: any failure returns
    ``False`` and the sandbox proceeds without a hard memory cap (never a hard
    crash from the cap mechanism itself).
    """
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.CreateJobObjectW.argtypes = (wintypes.LPVOID, wintypes.LPCWSTR)
        kernel32.SetInformationJobObject.restype = wintypes.BOOL
        kernel32.SetInformationJobObject.argtypes = (
            wintypes.HANDLE,
            ctypes.c_int,
            wintypes.LPVOID,
            wintypes.DWORD,
        )
        kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
        kernel32.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel32.CloseHandle.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)

        class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):  # noqa: N801
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_longlong),
                ("PerJobUserTimeLimit", ctypes.c_longlong),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class IO_COUNTERS(ctypes.Structure):  # noqa: N801
            _fields_ = [
                ("ReadOperationCount", ctypes.c_ulonglong),
                ("WriteOperationCount", ctypes.c_ulonglong),
                ("OtherOperationCount", ctypes.c_ulonglong),
                ("ReadTransferCount", ctypes.c_ulonglong),
                ("WriteTransferCount", ctypes.c_ulonglong),
                ("OtherTransferCount", ctypes.c_ulonglong),
            ]

        class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):  # noqa: N801
            _fields_ = [
                ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
                ("IoInfo", IO_COUNTERS),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        JOB_OBJECT_LIMIT_PROCESS_MEMORY = 0x00000100
        JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS = 9
        PROCESS_SET_QUOTA = 0x0100
        PROCESS_TERMINATE = 0x0001

        job = kernel32.CreateJobObjectW(None, None)
        if not job:
            return False
        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_PROCESS_MEMORY
        info.ProcessMemoryLimit = int(memory_mb) * 1024 * 1024
        ok = kernel32.SetInformationJobObject(
            job,
            JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS,
            ctypes.byref(info),
            ctypes.sizeof(info),
        )
        if not ok:
            kernel32.CloseHandle(job)
            return False
        proc = kernel32.OpenProcess(PROCESS_SET_QUOTA | PROCESS_TERMINATE, False, pid)
        if not proc:
            kernel32.CloseHandle(job)
            return False
        assigned = kernel32.AssignProcessToJobObject(job, proc)
        kernel32.CloseHandle(proc)
        kernel32.CloseHandle(job)
        return bool(assigned)
    except Exception:  # noqa: BLE001 — best-effort by design; never break the sandbox.
        return False


def _apply_memory_limit(proc: asyncio.subprocess.Process, memory_mb: int | None) -> bool:
    """Apply the hard memory cap. Returns True when cap is active/not requested."""
    if memory_mb is None:
        return True  # not requested — nothing to do
    if os.name == "nt":
        return _apply_windows_job_memory(proc.pid, memory_mb)
    return False  # POSIX: applied at spawn via preexec_fn


class CodeSandbox:
    """Runs program + tests in an isolated subprocess and returns a
    structured :class:`SandboxResult`.

    ``code`` provides the modules/functions under test; ``test_code`` must
    define a callable ``run_tests()`` that raises on failure. The program is
    defined first, then the test executes in a sibling namespace, so the test
    can call anything the program defined.
    """

    def __init__(self, *, timeout_seconds: float = 30.0, memory_mb: int | None = 256) -> None:
        self.timeout_seconds = timeout_seconds
        self.memory_mb = memory_mb

    async def run(
        self,
        code: str,
        test_code: str,
        *,
        timeout: float | None = None,
        memory_mb: int | None = None,
    ) -> SandboxResult:
        """Execute ``code`` + ``test_code`` in a fresh isolated subprocess.

        Never raises on test failures, timeouts, or blocked access — those
        are ordinary ``SandboxResult`` outcomes. Raises ``ValueError`` only
        for programmer error (non-positive timeout).
        """
        if not code or not test_code:
            return SandboxResult(
                passed=False,
                error="sandbox requires non-empty code and test_code",
            )
        effective_timeout = self.timeout_seconds if timeout is None else timeout
        if effective_timeout <= 0:
            raise ValueError("sandbox timeout must be positive")
        effective_memory = self.memory_mb if memory_mb is None else memory_mb

        root = Path(tempfile.mkdtemp(prefix="sage_sandbox_"))
        try:
            program_path = root / "program.py"
            test_path = root / "test_program.py"
            wrapper_path = root / "_sandbox_wrapper.py"
            result_path = root / "_sandbox_result.json"
            program_path.write_text(code, encoding="utf-8")
            test_path.write_text(test_code, encoding="utf-8")
            wrapper_path.write_text(_SANDBOX_WRAPPER, encoding="utf-8")

            started = time.perf_counter()
            preexec = (
                (lambda: _apply_posix_memory_preexec(effective_memory))  # type: ignore[misc]
                if os.name == "posix" and effective_memory
                else None
            )
            try:
                proc = await asyncio.create_subprocess_exec(
                    sys.executable,
                    "-I",
                    "-S",
                    str(wrapper_path),
                    str(root),
                    cwd=str(root),
                    env=_sandbox_env(root),
                    stdin=DEVNULL,
                    stdout=PIPE,
                    stderr=PIPE,
                    preexec_fn=preexec,
                )
            except OSError as exc:
                return SandboxResult(
                    passed=False,
                    error=f"sandbox could not launch interpreter: {exc}",
                    duration_seconds=time.perf_counter() - started,
                )

            cap_active = _apply_memory_limit(proc, effective_memory)
            if effective_memory and not cap_active:
                log.warning(
                    "code_sandbox.memory_limit_unavailable",
                    platform=sys.platform,
                    memory_mb=effective_memory,
                )

            try:
                out, err = await asyncio.wait_for(
                    proc.communicate(), timeout=effective_timeout
                )
            except TimeoutError:
                proc.kill()
                out, err = await proc.communicate()
                return SandboxResult(
                    passed=False,
                    output=_decode(out),
                    error=(
                        f"sandbox timed out after {effective_timeout:g}s "
                        "and was killed"
                    ),
                    duration_seconds=time.perf_counter() - started,
                )

            duration = time.perf_counter() - started
            if result_path.exists():
                data = json.loads(result_path.read_text(encoding="utf-8"))
                return SandboxResult(
                    passed=bool(data.get("passed")),
                    output=str(data.get("output") or ""),
                    error=data.get("error"),
                    duration_seconds=duration,
                )
            # No structured result: the child died hard (e.g. memory cap / crash).
            return SandboxResult(
                passed=False,
                output=_decode(out),
                error=_decode(err) or f"sandbox crashed (exit {proc.returncode})",
                duration_seconds=duration,
            )
        finally:
            shutil.rmtree(root, ignore_errors=True)


# -- Child-side bootstrap ------------------------------------------------------
# Runs ONLY inside the isolated subprocess. Un-typchecked by design: it is a
# string payload executed by a fresh interpreter, never part of SAGE's runtime.

_SANDBOX_WRAPPER = r'''\
"""Sandbox child bootstrap — ONLY ever runs inside the isolated subprocess.

argv[1] = the sandbox root (its own temp dir). Loads program.py and
test_program.py from that directory with all hardeners active, then writes
_sandbox_result.json so the parent can read a structured outcome even if the
child is later killed.
"""
from __future__ import annotations

import contextlib as _contextlib
import io as _io
import json as _json
import os as _os
import sys as _sys
import time as _time
import traceback as _traceback

_BOOTSTRAP_OPEN = open  # original, captured before any guard is installed
_ROOT = _os.path.realpath(_sys.argv[1])
_os.chdir(_ROOT)


def _block_network() -> None:
    """Replace Python's well-known network entry points so generated code
    cannot open outbound connections at the interpreted level."""
    import socket as _socket

    class _Disabled:
        def __init__(self, *args: object, **kwargs: object) -> None:
            raise OSError("network access is disabled in the sage sandbox")

        def __getattr__(self, name: str) -> object:
            raise OSError("network access is disabled in the sage sandbox")

    _disabled = _Disabled
    for _attr in (
        "socket", "socketpair", "create_connection", "create_server",
        "getaddrinfo", "gethostbyname", "gethostbyname_ex", "gethostbyaddr",
        "getnameinfo",
    ):
        if hasattr(_socket, _attr):
            setattr(_socket, _attr, _disabled)
    for _modname, _attrs in (
        ("http.client", ("HTTPConnection", "HTTPSConnection")),
        ("urllib.request", ("urlopen", "Request", "build_opener", "install_opener")),
        ("ssl", ("create_default_context", "wrap_socket", "SSLSocket")),
    ):
        try:
            _mod = __import__(_modname, fromlist=["*"])
        except Exception:
            continue
        for _attr in _attrs:
            if hasattr(_mod, _attr):
                setattr(_mod, _attr, _disabled)


def _block_process_spawning() -> None:
    """Forbid loading new processes — the primary escape hatch for network"""
    import os as _os_mod
    import subprocess as _subprocess

    def _disabled(*args: object, **kwargs: object) -> object:
        raise RuntimeError("process spawning is disabled in the sage sandbox")

    _subprocess.Popen = _disabled  # type: ignore[assignment]
    _subprocess.call = _disabled  # type: ignore[assignment]
    _subprocess.check_call = _disabled  # type: ignore[assignment]
    _subprocess.check_output = _disabled  # type: ignore[assignment]
    _subprocess.run = _disabled  # type: ignore[assignment]
    for _name in (
        "system", "popen", "spawnl", "spawnle", "spawnlp", "spawnlpe",
        "spawnv", "spawnve", "spawnvp", "spawnvpe", "fork", "forkpty",
    ):
        if hasattr(_os_mod, _name):
            setattr(_os_mod, _name, _disabled)


def _install_fs_guard() -> None:
    """Confine generated-code filesystem access to _ROOT (stdlib readable)."""
    import builtins as _builtins
    import io as _io_mod
    import os as _os_mod

    _real_open = _builtins.open
    _real_io_open = _io_mod.open
    _real_os_open = _os_mod.open

    _read_roots = {
        _os.path.realpath(p)
        for p in (_sys.prefix, _sys.base_prefix, _os.path.dirname(_sys.executable))
        if p
    }
    _root = _ROOT.rstrip("\\/") + _os.sep

    def _describe(path_object: object) -> str:
        try:
            return str(_os.fspath(path_object))  # type: ignore[arg-type]
        except Exception:
            return repr(path_object)

    def _allowed(path_object: object, writing: bool) -> bool:
        try:
            resolved = _os.path.realpath(_os.fspath(path_object))  # type: ignore[arg-type]
        except (TypeError, ValueError, OSError):
            return False
        if resolved == _ROOT or resolved.startswith(_root):
            return True
        if writing:
            return False
        return any(resolved.startswith(r) for r in _read_roots)

    def _guarded_open(file_object: object, mode: str = "r", *args: object, **kwargs: object):
        writing = any(c in mode for c in "wax+")
        if not _allowed(file_object, writing):
            raise PermissionError(
                "sandbox: filesystem access outside the sandbox root is "
                f"forbidden: {_describe(file_object)}"
            )
        return _real_open(file_object, mode, *args, **kwargs)  # type: ignore[call-arg]

    def _guarded_os_open(path_object: object, flags: int, *args: object, **kwargs: object):
        writing = bool(flags & (_os_mod.O_WRONLY | _os_mod.O_RDWR | _os_mod.O_APPEND
                                | _os_mod.O_CREAT | _os_mod.O_TRUNC))
        if not _allowed(path_object, writing):
            raise PermissionError(
                "sandbox: filesystem access outside the sandbox root is "
                f"forbidden: {_describe(path_object)}"
            )
        return _real_os_open(path_object, flags, *args, **kwargs)  # type: ignore[call-arg]

    def _make_mutation_guard(name: str):
        _real = getattr(_os_mod, name)

        def _guard(*args: object, **kwargs: object):
            if args and not _allowed(args[0], True):
                raise PermissionError(
                    "sandbox: filesystem mutation outside the sandbox root "
                    f"is forbidden: {_describe(args[0])}"
                )
            return _real(*args, **kwargs)

        return _guard

    _builtins.open = _guarded_open
    _io_mod.open = _guarded_open
    _os_mod.open = _guarded_os_open
    for _name in (
        "remove", "unlink", "rename", "replace", "rmdir", "mkdir", "makedirs",
        "chmod", "chown", "symlink", "unlink",
    ):
        if hasattr(_os_mod, _name):
            setattr(_os_mod, _name, _make_mutation_guard(_name))


def _load_and_run() -> None:
    program_src = _BOOTSTRAP_OPEN(_os.path.join(_ROOT, "program.py"), "r", encoding="utf-8").read()
    test_src = _BOOTSTRAP_OPEN(_os.path.join(_ROOT, "test_program.py"), "r", encoding="utf-8").read()

    _install_fs_guard()
    _block_network()
    _block_process_spawning()

    program_file = _os.path.join(_ROOT, "program.py")
    test_file = _os.path.join(_ROOT, "test_program.py")
    program_ns: dict = {"__name__": "__main__", "__file__": program_file}

    exec(compile(program_src, program_file, "exec"), program_ns)
    # The test executes with the program's namespace as its globals, so it
    # sees every name the program defined (no import ceremony required).
    test_ns: dict = dict(program_ns)
    test_ns["__name__"] = "__sandbox_test__"
    test_ns["__file__"] = test_file
    exec(compile(test_src, test_file, "exec"), test_ns)
    run_tests = test_ns.get("run_tests")
    if run_tests is None or not callable(run_tests):
        raise RuntimeError("sandbox test_code must define a callable run_tests()")
    run_tests()


def _main() -> int:
    started = _time.perf_counter()
    out_buf = _io.StringIO()
    passed = False
    error: str | None = None
    try:
        with _contextlib.redirect_stdout(out_buf), _contextlib.redirect_stderr(out_buf):
            _load_and_run()
        passed = True
    except BaseException:
        error = _traceback.format_exc()
    finally:
        result = {
            "passed": passed,
            "output": out_buf.getvalue(),
            "error": error,
            "duration_seconds": _time.perf_counter() - started,
        }
        with _BOOTSTRAP_OPEN(_os.path.join(_ROOT, "_sandbox_result.json"), "w", encoding="utf-8") as fp:
            _json.dump(result, fp)
    return 0 if passed else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())
'''
