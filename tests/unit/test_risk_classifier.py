"""Unit tests for the deterministic risk classifier (Phase 4).

Every HIGH-risk rule from the spec gets at least one test proving it forces
HIGH, plus tests proving genuinely low-risk new files classify LOW.
The classifier is a pure rules engine (no I/O, no model calls).
"""

from __future__ import annotations

import pytest
from sage.core.risk_classifier import ProposedChange, RiskLevel, classify


def low_change(path: str) -> ProposedChange:
    return ProposedChange(file_path=path, is_new_file=True, diff_or_content="x")


def edit_change(path: str) -> ProposedChange:
    return ProposedChange(file_path=path, is_new_file=False, diff_or_content="x")


# -- LOW risk: genuinely new files in eligible locations ----------------------


@pytest.mark.parametrize(
    "path",
    [
        "sage/agents/my_helper.py",
        "sage/tools/my_tool.py",
        "sage/skills/my_skill.py",
        "sage/knowledge/new_index.py",
        "sage/planning/new_heuristic.py",
    ],
)
def test_new_files_in_eligible_locations_are_low(path: str) -> None:
    assert classify(low_change(path)) is RiskLevel.LOW


def test_windows_style_new_path_is_low() -> None:
    change = ProposedChange(
        file_path="D:\\repo\\sage\\tools\\win_tool.py",
        is_new_file=True,
        diff_or_content="x",
    )
    assert classify(change) is RiskLevel.LOW


# -- HIGH: any edit to an existing file --------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "sage/agents/my_helper.py",
        "sage/tools/my_tool.py",
        "sage/skills/my_skill.py",
        "sage/knowledge/existing.py",
        "README.md",
    ],
)
def test_edits_to_existing_files_are_always_high(path: str) -> None:
    assert classify(edit_change(path)) is RiskLevel.HIGH


# -- HIGH: protected subsystem directories ------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "sage/core/new_module.py",
        "sage/memory/new_store.py",
        "sage/evolver/new_variant.py",
        "sage/soup/new_scorer.py",
        "sage/api/new_endpoint.py",
    ],
)
def test_new_files_in_protected_dirs_are_high(path: str) -> None:
    assert classify(low_change(path)) is RiskLevel.HIGH


def test_existing_file_in_protected_dir_is_high() -> None:
    assert classify(edit_change("sage/core/engine.py")) is RiskLevel.HIGH


# -- HIGH: the auto-coder's own safety mechanism ------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "sage/core/code_sandbox.py",
        "sage/core/risk_classifier.py",
        "sage/core/code_gate.py",
    ],
)
def test_own_safety_mechanism_files_are_high_even_when_new(path: str) -> None:
    assert classify(low_change(path)) is RiskLevel.HIGH
    assert classify(edit_change(path)) is RiskLevel.HIGH


# -- HIGH: auth / config related ----------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "sage/config/settings.py",
        "sage/secrets/vault.py",
        "sage/permissions/service.py",
        "sage/auth/login.py",
        "sage/agents/token_rotator.py",
        "sage/tools/credential_helper.py",
        "sage/skills/password_checker.py",
        "config_loader.py",
        ".env",
        ".env.example",
        "sage.yaml",
    ],
)
def test_auth_config_and_env_files_are_high(path: str) -> None:
    assert classify(low_change(path)) is RiskLevel.HIGH


# -- HIGH: dependency manifests -----------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "pyproject.toml",
        "requirements.txt",
        "requirements-dev.txt",
        "setup.py",
        "setup.cfg",
        "package.json",
        "package-lock.json",
        "yarn.lock",
        "poetry.lock",
    ],
)
def test_dependency_manifests_are_high(path: str) -> None:
    assert classify(low_change(path)) is RiskLevel.HIGH


# -- HIGH: ambiguous / unparseable input defaults to HIGH ---------------------


@pytest.mark.parametrize("path", ["", "   ", "../sage/tools/evil.py", "~/secret.py"])
def test_ambiguous_paths_default_to_high(path: str) -> None:
    assert classify(low_change(path)) is RiskLevel.HIGH


def test_non_string_path_defaults_to_high() -> None:
    change = ProposedChange(file_path=None, is_new_file=True)  # type: ignore[arg-type]
    assert classify(change) is RiskLevel.HIGH
