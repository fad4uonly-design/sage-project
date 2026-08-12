from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_requested_phase_one_documents_exist() -> None:
    required = [
        "README.md",
        "docs/architecture-specification.md",
        "docs/component-contracts.md",
        "docs/data-models.md",
        "docs/security-and-approval.md",
        "docs/test-strategy.md",
        "docs/qwen3-ollama-validation-plan.md",
        "schemas/integration-package.schema.json",
        "schemas/capability-registry.schema.json",
        "src/model_integration_engine/domain.py",
        "src/model_integration_engine/contracts.py",
    ]
    missing = [path for path in required if not (ROOT / path).is_file()]
    assert not missing


def test_main_spec_addresses_all_major_subsystems() -> None:
    text = (ROOT / "docs/architecture-specification.md").read_text(encoding="utf-8").lower()
    terms = [
        "model discovery",
        "artifact and runtime inspection",
        "capability detection",
        "compatibility engine",
        "adapter engine",
        "sandbox",
        "evaluation",
        "integration package",
        "approval gate",
        "regression testing",
        "capability registry",
    ]
    missing = [term for term in terms if term not in text]
    assert not missing
