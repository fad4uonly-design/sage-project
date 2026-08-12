from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import ValidationError

ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = ROOT / "schemas"
EXAMPLES = SCHEMAS / "examples"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def validator(schema_name: str) -> Draft202012Validator:
    schema = load(SCHEMAS / schema_name)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def test_schemas_are_valid_draft_2020_12() -> None:
    for schema_name in (
        "integration-package.schema.json",
        "capability-registry.schema.json",
    ):
        Draft202012Validator.check_schema(load(SCHEMAS / schema_name))


def test_integration_package_example_validates() -> None:
    validator("integration-package.schema.json").validate(
        load(EXAMPLES / "integration-package.example.json")
    )


def test_registry_example_validates() -> None:
    validator("capability-registry.schema.json").validate(
        load(EXAMPLES / "capability-registry.example.json")
    )


def test_inference_alone_cannot_be_marked_validated() -> None:
    document = load(EXAMPLES / "integration-package.example.json")
    claim = copy.deepcopy(document["capabilities"][1])
    claim["support"] = "SUPPORTED"
    claim["validation"] = "VALIDATED"
    claim["evidence_levels"] = ["INFERRED"]
    claim["evidence_ids"] = ["ev-provider-hypothesis"]
    document["capabilities"] = [claim]

    with pytest.raises(ValidationError):
        validator("integration-package.schema.json").validate(document)


def test_validated_test_evidence_must_be_a_passing_test_result() -> None:
    document = load(EXAMPLES / "integration-package.example.json")
    evidence = document["evidence"][2]
    assert evidence["level"] == "VALIDATED_BY_TEST"
    evidence["outcome"] = "FAIL"

    with pytest.raises(ValidationError):
        validator("integration-package.schema.json").validate(document)


def test_approved_package_requires_complete_scope_and_actor() -> None:
    document = load(EXAMPLES / "integration-package.example.json")
    document["approval"]["state"] = "APPROVED"
    # Scope, actor, timestamp, and event remain null.

    with pytest.raises(ValidationError):
        validator("integration-package.schema.json").validate(document)


def test_registry_rejects_unvalidated_active_capability() -> None:
    document = load(EXAMPLES / "capability-registry.example.json")
    document["entries"][0]["capabilities"][0]["validation"] = "UNVALIDATED"

    with pytest.raises(ValidationError):
        validator("capability-registry.schema.json").validate(document)


def test_registry_rejects_capability_without_test_evidence_level() -> None:
    document = load(EXAMPLES / "capability-registry.example.json")
    document["entries"][0]["capabilities"][0]["evidence_levels"] = [
        "DETECTED_FROM_METADATA"
    ]

    with pytest.raises(ValidationError):
        validator("capability-registry.schema.json").validate(document)
