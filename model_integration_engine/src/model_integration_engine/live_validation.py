"""Opt-in live Ollama evidence collection hook.

This command performs read-only discovery and model-detail inspection. It does
not run behavioral probes until a production security sandbox backend is wired.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from .plugins.ollama.client import OllamaClient, StdlibJsonTransport
from .plugins.ollama.discovery import OllamaDiscoveryProvider
from .plugins.ollama.inspection import OllamaModelInspector


async def collect(endpoint: str, model_reference: str) -> dict:
    client = OllamaClient(endpoint, StdlibJsonTransport(), timeout_seconds=30)
    discovery = await OllamaDiscoveryProvider(client).discover_all()
    if discovery.problem is not None or discovery.runtime is None:
        raise RuntimeError(
            discovery.problem.message if discovery.problem else "runtime not discovered"
        )
    matches = [
        item for item in discovery.models if item.runtime_reference == model_reference
    ]
    if len(matches) != 1:
        raise RuntimeError("exact runtime model reference must resolve once")
    inspection = await OllamaModelInspector(client).inspect_model(matches[0])
    if inspection.problem is not None or inspection.details is None:
        raise RuntimeError(
            inspection.problem.message if inspection.problem else "inspection failed"
        )
    evidence = discovery.evidence + inspection.evidence
    return {
        "schema_version": "0.3.0",
        "state": "LIVE_METADATA_COLLECTED_PROBES_BLOCKED_NO_PRODUCTION_SANDBOX",
        "live": True,
        "runtime": {
            "runtime_id": discovery.runtime.subject.subject_id,
            "version": discovery.runtime.version,
            "endpoint": discovery.runtime.endpoint,
        },
        "deployment": {
            "deployment_id": matches[0].deployment_subject.subject_id,
            "runtime_reference": matches[0].runtime_reference,
            "content_digest": matches[0].content_digest,
            "identity_status": matches[0].identity_status,
        },
        "inspection": {
            "architecture": inspection.details.architecture,
            "context_length": inspection.details.context_length,
            "tokenizer_model": inspection.details.tokenizer_model,
            "declared_capabilities": list(inspection.details.declared_capabilities),
            "unknowns": list(inspection.details.unknowns),
            "raw_response_digest": inspection.details.raw_response_digest,
        },
        "evidence": [
            {
                "evidence_id": item.evidence_id,
                "kind": item.kind.value,
                "level": item.level.value,
                "subject_id": item.subject.subject_id,
                "observation_key": item.observation_key,
                "observed_value": item.observed_value,
                "source": {
                    "uri": item.source.uri,
                    "digest": item.source.digest,
                    "locator": item.source.locator,
                },
                "collector_id": item.collector_id,
                "collector_version": item.collector_version,
                "collected_at": item.collected_at.isoformat(),
            }
            for item in evidence
        ],
        "limitations": [
            "No behavioral capability was validated.",
            "No production sandbox backend is configured by this command.",
            "No integration, approval, application, or registry write occurred.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Collect live read-only Ollama metadata evidence")
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--model", required=True, help="Exact runtime model reference")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    document = asyncio.run(collect(args.endpoint, args.model))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
