"""Experiment execution (application layer).

This is where research procedures live: the architecture-inspection experiment
for Research Specimen 001, its inspector, and the builder that turns an
architecture map into Layer-1 Model Knowledge records.

Later milestones (behavioral, activation, representation, causal research) plug
in here without restructuring the domain or interface layers.
"""

from .architecture_inspector import HeuristicArchitectureInspector
from .inspection import (
    EnvironmentInfo,
    InspectionReport,
    ModelInspectionExperiment,
    stable_report_id,
)
from .model_knowledge import build_model_knowledge

__all__ = [
    "HeuristicArchitectureInspector",
    "build_model_knowledge",
    "EnvironmentInfo",
    "InspectionReport",
    "ModelInspectionExperiment",
    "stable_report_id",
]
