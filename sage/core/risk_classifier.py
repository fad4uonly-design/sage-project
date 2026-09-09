"""Risk classifier — deterministic rules engine for auto-generated code.

Phase 4 safety-critical path. Risk classification decides whether a generated
change may be auto-applied without human approval, so it MUST be a pure,
reproducible rules engine — never an LLM call. Every rule below is a
keyword/path match with no randomness.

Rules (implemented exactly; ambiguity always defaults to HIGH):

* **LOW** (auto-apply eligible): new files only, in ``sage/agents/``,
  ``sage/tools/``, ``sage/skills/``, or genuinely new files anywhere else
  that the HIGH rules below do not catch.
* **HIGH** (always requires approval, regardless of test results):
  * any edit to an *existing* file, anywhere;
  * any file under ``sage/core/``, ``sage/memory/``, ``sage/evolver/``,
    ``sage/soup/``, ``sage/api/``, or anything auth-/config-related;
  * the auto-coder's own files (this module, the sandbox, the gate) — the
    auto-coder must never be able to modify its own safety mechanism;
  * dependency manifests (``pyproject.toml``, ``requirements*``, lockfiles…);
  * anything the classifier cannot confidently categorize.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


#: Risk levels. HIGH requires explicit human approval before any write.
class RiskLevel(str, Enum):
    LOW = "low"
    HIGH = "high"


@dataclass(frozen=True)
class ProposedChange:
    """A proposed auto-coder change awaiting classification.

    ``diff_or_content`` carries the *full proposed file content* — the gate
    writes exactly this string to ``file_path`` when it applies.
    """

    file_path: str
    is_new_file: bool = False
    diff_or_content: str = ""
    description: str = ""


#: The auto-coder's own safety mechanism. The auto-coder must NEVER be able to
#: modify these — a self-modifying safety mechanism is no safety at all.
GATE_OWN_FILES = frozenset(
    {
        "sage/core/code_sandbox.py",
        "sage/core/risk_classifier.py",
        "sage/core/code_gate.py",
    }
)

#: Protected subsystems — any file under these dirs is HIGH regardless of
#: whether it is new or an edit.
PROTECTED_DIRS = frozenset(
    {
        "sage/core",
        "sage/memory",
        "sage/evolver",
        "sage/soup",
        "sage/api",
    }
)

#: Auth/config-related path segments — matched as substrings anywhere in the
#: normalized path. Covers sage/config/*, sage/secrets/*, sage/permissions/*,
#: *_settings.py, config_*.py, tokens, credentials, passwords, etc.
AUTH_CONFIG_KEYWORDS = (
    "auth",
    "config",
    "secret",
    "permission",
    "setting",
    "token",
    "credential",
    "password",
    "passwd",
)

#: Dependency / build manifests. Touching any of these is HIGH, even a "new"
#: dependency file (adding a dependency changes the whole runtime).
DEPENDENCY_FILES = frozenset(
    {
        "pyproject.toml",
        "requirements.txt",
        "requirements-dev.txt",
        "requirements-test.txt",
        "setup.py",
        "setup.cfg",
        "uv.lock",
        "poetry.lock",
        "Pipfile",
        "Pipfile.lock",
        "package.json",
        "package-lock.json",
        "pnpm-lock.yaml",
        "yarn.lock",
    }
)

#: Environment / deployment coordinate files (always HIGH).
ENV_COORDINATE_FILES = frozenset({"sage.yaml", "sage.yml"})

_DRIVE_RE = re.compile(r"^[A-Za-z]:")


def _normalize(file_path: str) -> str:
    """Normalize a Windows or POSIX relative path to a bare forward-slash
    relative path (``C:\\sage\\agents\\x.py`` -> ``sage/agents/x.py``).
    Returns ``""`` for empty/unparseable input, which classifies HIGH."""
    if not isinstance(file_path, str) or not file_path.strip():
        return ""
    path = file_path.replace("\\", "/").strip()
    path = _DRIVE_RE.sub("", path)
    path = path.lstrip("/")
    segments = [seg for seg in path.split("/") if seg and seg != "."]
    return "/".join(segments)


def classify_with_reason(change: ProposedChange) -> tuple[RiskLevel, str]:
    """Classify a change and return ``(level, human-readable rule hit)``."""
    path = _normalize(change.file_path)

    if not path:
        return RiskLevel.HIGH, "empty or unparseable file path — ambiguous, defaulting to HIGH"

    segments = path.split("/")
    if ".." in segments or "~" in segments:
        return (
            RiskLevel.HIGH,
            f"path escapes or is ambiguous ('..'/'~' segments): {path!r}",
        )

    basename = segments[-1]

    # The auto-coder's own safety mechanism — non-negotiable.
    if path in GATE_OWN_FILES:
        return (
            RiskLevel.HIGH,
            f"change targets the auto-coder's own safety mechanism: {path}",
        )

    # Dependency / build manifests.
    if basename in DEPENDENCY_FILES:
        return RiskLevel.HIGH, f"change touches a dependency manifest: {basename}"

    # Env / deployment coordinate files (".env", ".env.example", "sage.yaml"...).
    if basename.startswith(".env") or basename in ENV_COORDINATE_FILES:
        return RiskLevel.HIGH, f"change touches an environment/config coordinate file: {basename}"

    # Anything auth/config-related anywhere in the path.
    lowered_segments = [seg.lower() for seg in segments]
    for seg in lowered_segments:
        if any(keyword in seg for keyword in AUTH_CONFIG_KEYWORDS):
            return (
                RiskLevel.HIGH,
                f"change touches an auth/config-related path segment ({seg!r}): {path}",
            )

    # Protected subsystem directories.
    if len(segments) >= 2 and segments[0] == "sage":
        prefix = "/".join(segments[:2])
        if prefix in PROTECTED_DIRS:
            return RiskLevel.HIGH, f"change targets a protected subsystem directory: {prefix}"

    # Edits to existing files are never auto-apply eligible, anywhere.
    if not change.is_new_file:
        return (
            RiskLevel.HIGH,
            f"change edits an existing file ({path}) — only new files are auto-apply eligible",
        )

    return RiskLevel.LOW, f"new file in an auto-apply-eligible location: {path}"


def classify(change: ProposedChange) -> RiskLevel:
    """Return the risk level for a proposed change (deterministic, no I/O)."""
    level, _ = classify_with_reason(change)
    return level
