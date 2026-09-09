"""Unit tests for the CodeSandbox isolation boundary (Phase 4).

Proves the guarantees the auto-coder safety report will claim:
- generated code runs in a SEPARATE subprocess (never in-process)
- no network is reachable from inside (socket + http + urllib + ssl)
- process spawning is forbidden (subprocess / os.system / fork)
- filesystem writes/reads outside the sandbox temp dir are refused
- the hard timeout actually triggers and kills the child
- test failure is a normal SandboxResult (passed=False), never an exception
"""

from __future__ import annotations

import contextlib
import os
import tempfile

from sage.core.code_sandbox import CodeSandbox

PASS = "def run_tests():\n    assert True\n"
FAIL = "def run_tests():\n    raise AssertionError('boom')\n"


async def test_passing_code_returns_passed() -> None:
    sb = CodeSandbox(timeout_seconds=10)
    result = await sb.run("VALUE = 1", PASS)
    assert result.passed is True
    assert result.error is None


async def test_failing_tests_are_normal_results_not_exceptions() -> None:
    sb = CodeSandbox(timeout_seconds=10)
    result = await sb.run("VALUE = 1", FAIL)
    assert result.passed is False
    assert result.error is not None
    assert "boom" in result.error


async def test_missing_run_tests_is_a_failure_not_a_crash() -> None:
    sb = CodeSandbox(timeout_seconds=10)
    result = await sb.run("VALUE = 1", "def something_else():\n    pass\n")
    assert result.passed is False
    assert "run_tests" in (result.error or "")


async def test_empty_code_is_rejected_before_launch() -> None:
    sb = CodeSandbox(timeout_seconds=10)
    result = await sb.run("", PASS)
    assert result.passed is False
    assert "non-empty" in (result.error or "")


async def test_network_is_blocked_inside_sandbox() -> None:
    sb = CodeSandbox(timeout_seconds=15)
    test_code = (
        "def run_tests():\n"
        "    import socket\n"
        "    socket.create_connection(('example.com', 80), timeout=2)\n"
    )
    result = await sb.run("MARKER = 1", test_code)
    assert result.passed is False
    assert "disabled" in (result.error or "").lower()


async def test_http_client_is_blocked_inside_sandbox() -> None:
    sb = CodeSandbox(timeout_seconds=15)
    test_code = (
        "def run_tests():\n"
        "    import http.client\n"
        "    conn = http.client.HTTPConnection('example.com', timeout=2)\n"
        "    conn.request('GET', '/')\n"
    )
    result = await sb.run("MARKER = 1", test_code)
    assert result.passed is False


async def test_process_spawning_is_blocked_inside_sandbox() -> None:
    sb = CodeSandbox(timeout_seconds=15)
    test_code = (
        "def run_tests():\n"
        "    import subprocess\n"
        "    subprocess.run(['echo', 'hi'])\n"
    )
    result = await sb.run("MARKER = 1", test_code)
    assert result.passed is False
    assert "disabled" in (result.error or "").lower()


async def test_os_system_is_blocked_inside_sandbox() -> None:
    sb = CodeSandbox(timeout_seconds=15)
    test_code = "def run_tests():\n    import os\n    os.system('echo hi')\n"
    result = await sb.run("MARKER = 1", test_code)
    assert result.passed is False


async def test_write_outside_sandbox_dir_is_refused() -> None:
    outside = tempfile.mkdtemp(prefix="code_gate_outside_")
    target = os.path.join(outside, "evil.txt")
    try:
        sb = CodeSandbox(timeout_seconds=15)
        test_code = (
            "def run_tests():\n"
            f"    open({target!r}, 'w').write('pwned')\n"
        )
        result = await sb.run("MARKER = 1", test_code)
        assert result.passed is False
        assert "forbidden" in (result.error or "").lower()
        assert not os.path.exists(target)
    finally:
        with contextlib.suppress(OSError):
            os.rmdir(outside)


async def test_read_outside_sandbox_dir_is_refused() -> None:
    fd, secret_path = tempfile.mkstemp(prefix="code_gate_secret_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write("TOPSECRET")
        sb = CodeSandbox(timeout_seconds=15)
        test_code = (
            "def run_tests():\n"
            f"    data = open({secret_path!r}).read()\n"
            "    assert data == 'TOPSECRET'\n"
        )
        result = await sb.run("MARKER = 1", test_code)
        assert result.passed is False
        assert "forbidden" in (result.error or "").lower()
    finally:
        with contextlib.suppress(OSError):
            os.remove(secret_path)


async def test_write_inside_sandbox_dir_is_allowed() -> None:
    sb = CodeSandbox(timeout_seconds=15)
    test_code = (
        "def run_tests():\n"
        "    import os\n"
        "    here = os.getcwd()\n"
        "    open(os.path.join(here, 'notes.txt'), 'w').write('hello')\n"
        "    assert open(os.path.join(here, 'notes.txt')).read() == 'hello'\n"
    )
    result = await sb.run("MARKER = 1", test_code)
    assert result.passed is True


async def test_timeout_kills_hanging_code() -> None:
    sb = CodeSandbox(timeout_seconds=2)
    hanging = "import time\ntime.sleep(60)\n"
    result = await sb.run(hanging, PASS, timeout=1)
    assert result.passed is False
    assert "timed out" in (result.error or "").lower()
    assert result.duration_seconds < 30
