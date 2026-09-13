"""Generic ingestion of explicitly user-supplied acceptance observations.

User input is preserved as ``EvidenceKind.USER_INPUT`` and can never become
``VALIDATED_BY_TEST`` through this collector.  The claimed evidence level is
retained only for classification; callers must keep these records separate from
live collector evidence and must not use them as behavioral validation.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from .domain import (
    EvidenceKind,
    EvidenceLevel,
    EvidenceOutcome,
    EvidenceRecord,
    JSONValue,
    SubjectKind,
    SubjectRef,
)
from .evidence import EvidenceFactory, sha256_digest, utc_now

_ALLOWED_LEVELS = {
    EvidenceLevel.DETECTED_FROM_METADATA,
    EvidenceLevel.DETECTED_FROM_RUNTIME,
    EvidenceLevel.INFERRED,
    EvidenceLevel.UNKNOWN,
}


@dataclass(slots=True)
class UserInputEvidenceCollector:
    """Convert a bounded JSON document into provenance-preserving evidence."""

    clock: callable = utc_now
    collector_id: str = "mie.evidence.user-input"
    collector_version: str = "0.3.0"
    max_observations: int = 10_000

    def collect(
        self,
        document: Mapping[str, JSONValue] | None,
        *,
        subjects: Mapping[SubjectKind, SubjectRef],
        default_environment_id: str | None = None,
    ) -> tuple[EvidenceRecord, ...]:
        if document is None:
            return ()
        if document.get("schema_version") != "0.1.0":
            raise ValueError("user evidence requires schema_version 0.1.0")
        source_id = document.get("source_id")
        if not isinstance(source_id, str) or not source_id.strip():
            raise ValueError("user evidence requires a non-empty source_id")
        observations = document.get("observations")
        if not isinstance(observations, list):
            raise ValueError("user evidence observations must be an array")
        if len(observations) > self.max_observations:
            raise ValueError("user evidence exceeds the observation limit")

        document_digest = sha256_digest(dict(document))
        source_uri = (
            "urn:mie:user-input:"
            + sha256_digest(source_id).removeprefix("sha256:")[:32]
        )
        factory = EvidenceFactory(
            self.collector_id, self.collector_version, self.clock
        )
        records: list[EvidenceRecord] = []
        for index, raw in enumerate(observations):
            if not isinstance(raw, Mapping):
                raise ValueError(f"user observation {index} must be an object")
            try:
                subject_kind = SubjectKind(raw.get("subject_kind"))
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"user observation {index} has an invalid subject_kind"
                ) from exc
            subject = subjects.get(subject_kind)
            if subject is None:
                raise ValueError(
                    f"user observation {index} refers to unavailable subject {subject_kind.value}"
                )
            observation_key = raw.get("observation_key")
            if not isinstance(observation_key, str) or not observation_key.strip():
                raise ValueError(
                    f"user observation {index} requires an observation_key"
                )
            try:
                level = EvidenceLevel(raw.get("level", EvidenceLevel.UNKNOWN.value))
            except ValueError as exc:
                raise ValueError(
                    f"user observation {index} has an invalid evidence level"
                ) from exc
            if level not in _ALLOWED_LEVELS:
                raise ValueError(
                    "user input cannot claim VALIDATED_BY_TEST or NOT_SUPPORTED evidence"
                )
            if "value" not in raw:
                raise ValueError(f"user observation {index} requires a value")
            value = raw["value"]
            reported_at = raw.get("reported_observed_at")
            if reported_at is not None and not isinstance(reported_at, str):
                raise ValueError("reported_observed_at must be a string when supplied")
            environment_id = raw.get("environment_id", default_environment_id)
            if environment_id is not None and not isinstance(environment_id, str):
                raise ValueError("environment_id must be a string when supplied")
            records.append(
                factory.create(
                    kind=EvidenceKind.USER_INPUT,
                    level=level,
                    subject=subject,
                    observation_key=observation_key,
                    observed_value={
                        "classification": "USER_SUPPLIED",
                        "reported_value": value,
                        "reported_observed_at": reported_at,
                    },
                    source_uri=source_uri,
                    source_digest=document_digest,
                    locator=f"/observations/{index}",
                    outcome=EvidenceOutcome.NOT_APPLICABLE,
                    environment_id=environment_id,
                )
            )
        return tuple(records)
