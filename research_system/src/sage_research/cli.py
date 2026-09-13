"""Minimal command-line interface for the Model Lab.

Example::

    python -m sage_research inspect --model EleutherAI/pythia-70m
    sage-research inspect --model EleutherAI/pythia-70m --output ./out

The PyTorch loader is imported lazily; a helpful error is printed if the
``pytorch`` extra is not installed.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from .domain.model_artifact import LoadOptions, ModelArtifact, ModelFormat
from .version import __version__


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="sage-research",
        description="SAGE Research System — Model Lab (Research Specimen 001).",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect = subparsers.add_parser(
        "inspect",
        help="Architecture inspection of a model artifact (Milestone slice).",
    )
    inspect.add_argument("--model", required=True, help="Hugging Face repo id or local path")
    inspect.add_argument("--revision", default=None, help="Checkpoint revision (optional)")
    inspect.add_argument("--device", default="cpu", help="Device to load onto (default: cpu)")
    inspect.add_argument("--dtype", default=None, help="Optional dtype override (float16/bfloat16/... )")
    inspect.add_argument("--output", default="./sage_research_output", help="Output directory")
    inspect.add_argument("--name", default=None, help="Specimen name (default: last path segment)")

    args = parser.parse_args(argv)
    if args.command == "inspect":
        return _run_inspect(args)
    return 2


def _run_inspect(args: argparse.Namespace) -> int:
    from .experiments.architecture_inspector import HeuristicArchitectureInspector
    from .experiments.inspection import ModelInspectionExperiment
    from .infrastructure.json_repository import JsonKnowledgeRepository
    from .infrastructure.pytorch_loader import PyTorchModelLoader

    name = args.name or args.model.rstrip("/").split("/")[-1]
    artifact = ModelArtifact(
        name=name,
        family="pythia",
        source=f"huggingface:{args.model}",
        format=ModelFormat.ORIGINAL,
    )
    options = LoadOptions(revision=args.revision, device=args.device, dtype=args.dtype)

    output_dir = Path(args.output)
    knowledge_dir = output_dir / "knowledge"
    repository = JsonKnowledgeRepository(knowledge_dir)

    experiment = ModelInspectionExperiment(
        loader=PyTorchModelLoader(),
        inspector=HeuristicArchitectureInspector(),
        repository=repository,
    )

    try:
        report = experiment.run(
            artifact,
            options=options,
            rerun_configuration={
                "model": args.model,
                "revision": args.revision or "default",
                "device": args.device,
                "dtype": args.dtype or "default",
            },
        )
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "architecture_map.json").write_text(
        json.dumps(report.architecture_map.to_dict(), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (output_dir / "inspection_report.json").write_text(
        json.dumps(report.to_dict(), indent=2, sort_keys=True),
        encoding="utf-8",
    )

    _print_summary(report)
    print(f"\nWrote {len(report.knowledge_records)} Model Knowledge records to {knowledge_dir}/")
    print(f"Wrote architecture map and report JSON to {output_dir}/")
    return 0


def _print_summary(report) -> None:
    s = report.architecture_map.summary
    print("=" * 64)
    print("SAGE Research System — Architecture Inspection Report")
    print("=" * 64)
    print(f"Report ID          : {report.report_id}")
    print(f"Model identity     : {report.identity.slug}")
    print(f"Source             : {report.identity.source}")
    print(f"Architecture label : {s.architecture_label}")
    print(f"Total parameters   : {s.total_parameters:,}")
    print(f"Trainable          : {s.trainable_parameters:,}")
    print(f"Layers             : {s.num_layers}")
    print(f"Hidden size        : {s.hidden_size}")
    print(f"Vocabulary         : {s.vocab_size}")
    print(f"Attention heads    : {s.num_attention_heads}")
    print(f"Head dim           : {s.head_dim}")
    print(f"Intermediate size  : {s.intermediate_size}")
    print(f"LayerNorm epsilon  : {s.layer_norm_epsilon}")
    print("-" * 64)
    print("Components:")
    for kind, count in sorted(
        report.architecture_map.component_kind_counts().items(), key=lambda kv: kv[0].value
    ):
        print(f"  {kind.value:<14} {count}")
    print("-" * 64)
    print(f"Connections        : {len(report.architecture_map.connections)}")
    print(f"Knowledge records  : {len(report.knowledge_records)}")


if __name__ == "__main__":
    raise SystemExit(main())
