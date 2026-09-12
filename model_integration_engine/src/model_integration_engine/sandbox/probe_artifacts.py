"""Strict conversion from resolved sandbox artifacts to typed probe results."""

from __future__ import annotations

import json
from collections.abc import Mapping

from ..application.probes import ProbeKind, ProbePlan, RawProbeResult
from ..domain import JSONValue, TestOutcome
from .artifacts import ArtifactResolutionError, ResolvedArtifact, SecureArtifactResolver


class ProbeArtifactIngestor:
    media_type = "application/vnd.mie.probe-results+json"
    schema_version = "0.3.0"

    def ingest(
        self,
        *,
        artifact: ResolvedArtifact,
        resolver: SecureArtifactResolver,
        expected_plan: ProbePlan,
        expected_run_id: str,
    ) -> tuple[RawProbeResult, ...]:
        if artifact.media_type != self.media_type:
            raise ArtifactResolutionError(
                "PROBE_ARTIFACT_TYPE_MISMATCH", "Wrong probe result media type"
            )
        try:
            document = json.loads(resolver.read_verified(artifact))
        except json.JSONDecodeError as exc:
            raise ArtifactResolutionError(
                "PROBE_ARTIFACT_MALFORMED", "Probe artifact is not JSON"
            ) from exc
        if not isinstance(document, dict):
            raise ArtifactResolutionError(
                "PROBE_ARTIFACT_MALFORMED", "Probe artifact must be an object"
            )
        allowed_root = {"schema_version", "plan_id", "run_id", "results"}
        if set(document) != allowed_root:
            raise ArtifactResolutionError(
                "PROBE_ARTIFACT_UNEXPECTED_FIELDS", "Unexpected probe artifact fields"
            )
        if (
            document.get("schema_version") != self.schema_version
            or document.get("plan_id") != expected_plan.plan_id
            or document.get("run_id") != expected_run_id
        ):
            raise ArtifactResolutionError(
                "PROBE_ARTIFACT_BINDING_MISMATCH",
                "Probe artifact is not bound to the expected plan/run",
            )
        raw_results = document.get("results")
        if not isinstance(raw_results, list):
            raise ArtifactResolutionError(
                "PROBE_ARTIFACT_MALFORMED", "Probe results must be an array"
            )
        cases = {item.probe_id: item for item in expected_plan.cases}
        if {item.get("probe_id") for item in raw_results if isinstance(item, dict)} != set(cases):
            raise ArtifactResolutionError(
                "PROBE_ARTIFACT_CASE_MISMATCH",
                "Probe artifact cases differ from the approved plan",
            )

        results: list[RawProbeResult] = []
        for item in raw_results:
            if not isinstance(item, dict):
                raise ArtifactResolutionError(
                    "PROBE_ARTIFACT_MALFORMED", "Probe result must be an object"
                )
            allowed = {
                "probe_id",
                "kind",
                "subject",
                "outcome",
                "assertions",
                "measurements",
                "output_digest",
                "error_code",
                "error_message",
            }
            if set(item) != allowed:
                raise ArtifactResolutionError(
                    "PROBE_ARTIFACT_UNEXPECTED_FIELDS", "Unexpected probe result fields"
                )
            case = cases.get(item.get("probe_id"))
            if case is None or item.get("kind") != case.kind.value:
                raise ArtifactResolutionError(
                    "PROBE_ARTIFACT_CASE_MISMATCH", "Probe kind/ID mismatch"
                )
            subject_raw = item.get("subject")
            if not isinstance(subject_raw, dict) or set(subject_raw) != {
                "kind",
                "subject_id",
                "version",
                "digest",
            }:
                raise ArtifactResolutionError(
                    "PROBE_ARTIFACT_SUBJECT_INVALID", "Invalid probe subject"
                )
            if (
                subject_raw.get("kind") != case.subject.kind.value
                or subject_raw.get("subject_id") != case.subject.subject_id
                or subject_raw.get("digest") != case.subject.digest
            ):
                raise ArtifactResolutionError(
                    "PROBE_ARTIFACT_SUBJECT_MISMATCH",
                    "Probe result subject differs from the plan",
                )
            assertions = item.get("assertions")
            measurements = item.get("measurements")
            if not isinstance(assertions, dict) or not isinstance(measurements, dict):
                raise ArtifactResolutionError(
                    "PROBE_ARTIFACT_MALFORMED", "Assertions/measurements must be objects"
                )
            try:
                outcome = TestOutcome(item.get("outcome"))
            except ValueError as exc:
                raise ArtifactResolutionError(
                    "PROBE_ARTIFACT_OUTCOME_INVALID", "Invalid probe outcome"
                ) from exc
            results.append(
                RawProbeResult(
                    probe_id=case.probe_id,
                    kind=ProbeKind(item["kind"]),
                    subject=case.subject,
                    outcome=outcome,
                    assertions=_json_mapping(assertions),
                    measurements=_json_mapping(measurements),
                    output_digest=item.get("output_digest")
                    if isinstance(item.get("output_digest"), str)
                    else None,
                    error_code=item.get("error_code")
                    if isinstance(item.get("error_code"), str)
                    else None,
                    error_message=item.get("error_message")
                    if isinstance(item.get("error_message"), str)
                    else None,
                )
            )
        return tuple(results)


def _json_mapping(value: Mapping[str, object]) -> Mapping[str, JSONValue]:
    def convert(item):
        if item is None or isinstance(item, (str, int, float, bool)):
            return item
        if isinstance(item, list):
            return [convert(child) for child in item]
        if isinstance(item, dict):
            return {str(key): convert(child) for key, child in item.items()}
        raise ArtifactResolutionError(
            "PROBE_ARTIFACT_VALUE_INVALID", "Non-JSON probe value"
        )

    return {str(key): convert(item) for key, item in value.items()}
