"""Command-line entry point for generic real-deployment acceptance."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from .application.acceptance import AcceptanceConfig, GenericAcceptanceRunner
from .application.probe_backend import DockerProbeExecutionBackend
from .sandbox.docker import DockerSandboxBackend


def _load_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"unable to load {label}: {path}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _load_registry(path: Path) -> dict[str, Any]:
    value = _load_object(path, "registry snapshot")
    project_root = Path(__file__).resolve().parents[2]
    schema = json.loads(
        (project_root / "schemas" / "capability-registry.schema.json").read_text(
            encoding="utf-8"
        )
    )
    errors = list(
        Draft202012Validator(
            schema, format_checker=FormatChecker()
        ).iter_errors(value)
    )
    if errors:
        raise ValueError("registry snapshot is invalid: " + errors[0].message)
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Collect generic Ollama deployment evidence and create an immutable "
            "draft without requesting approval"
        )
    )
    parser.add_argument("--endpoint", required=True, help="Approved Ollama base URL")
    parser.add_argument(
        "--model", required=True, help="Exact discovered runtime model reference"
    )
    parser.add_argument("--artifact-path", type=Path)
    parser.add_argument(
        "--artifact-digest",
        help="Optional expected digest in sha256:<64 lowercase hex> form",
    )
    parser.add_argument("--registry-snapshot", type=Path)
    parser.add_argument("--user-evidence", type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    registry = (
        _load_registry(args.registry_snapshot) if args.registry_snapshot else None
    )
    user_evidence = (
        _load_object(args.user_evidence, "user evidence")
        if args.user_evidence
        else None
    )
    config = AcceptanceConfig(
        endpoint=args.endpoint,
        model_reference=args.model,
        output_directory=args.output_dir,
        artifact_path=args.artifact_path,
        artifact_digest=args.artifact_digest,
        registry_snapshot=registry,
        user_evidence_document=user_evidence,
        timeout_seconds=args.timeout_seconds,
    )
    sandbox = DockerSandboxBackend(
        allowlist_network="mie-allowlist-internal",
        gateway_endpoint="http://mie-gateway-test:18080",
        approved_upstream_endpoint="http://host.docker.internal:11434",
        collection_root=config.output_directory / "probe-collections",
    )
    probe_backend = DockerProbeExecutionBackend(
        sandbox=sandbox,
        worker_source=str(Path(__file__).resolve().parents[2] / "src"),
        artifact_store_root=config.output_directory / "probe-artifacts",
    )
    result = asyncio.run(
        GenericAcceptanceRunner(probe_backend=probe_backend).run(config)
    )
    print(f"state={result.state}")
    print(f"approval_requested={str(result.approval_requested).lower()}")
    print(f"output_directory={result.output_directory}")
    print(f"package_path={result.package_path or 'NOT_PRODUCED'}")
    print(f"package_digest={result.package_digest or 'NOT_PRODUCED'}")
    return 0 if result.package_path else 2


if __name__ == "__main__":
    raise SystemExit(main())
