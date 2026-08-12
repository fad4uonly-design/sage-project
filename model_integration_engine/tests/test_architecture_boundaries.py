from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src" / "model_integration_engine"


def source_files() -> list[Path]:
    return sorted(SOURCE.rglob("*.py"))


def test_core_contains_no_named_model_special_case() -> None:
    combined = "\n".join(path.read_text(encoding="utf-8") for path in source_files()).lower()
    assert "qwen" not in combined
    assert "if model ==" not in combined
    assert "if model_name ==" not in combined


def test_core_has_no_sage_dependency_or_write_binding() -> None:
    combined = "\n".join(path.read_text(encoding="utf-8") for path in source_files()).lower()
    assert "import sage" not in combined
    assert "from sage" not in combined
    assert "integrationapplier" not in combined


def test_domain_and_contract_layers_do_not_import_io_implementations() -> None:
    forbidden_roots = {
        "aiohttp",
        "httpx",
        "requests",
        "socket",
        "subprocess",
        "urllib",
    }
    violations: list[str] = []
    for path in (SOURCE / "domain.py", SOURCE / "contracts.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                if name.split(".")[0] in forbidden_roots:
                    violations.append(f"{path.name}: {name}")
    assert not violations


def test_named_validation_fixture_is_outside_core_source() -> None:
    plan = ROOT / "validation" / "qwen3-4b-ollama" / "plan.json"
    assert plan.is_file()
    assert not any("qwen" in path.name.lower() for path in SOURCE.rglob("*"))
