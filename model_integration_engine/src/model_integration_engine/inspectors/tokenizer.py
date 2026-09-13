"""Generic tokenizer metadata interpretation with open-world semantics."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from ..domain import (
    EvidenceKind,
    EvidenceLevel,
    EvidenceOutcome,
    EvidenceRecord,
    JSONValue,
    SubjectRef,
)
from ..evidence import EvidenceFactory, utc_now
from .gguf import GGUFArray, GGUFMetadataValue


@dataclass(frozen=True, slots=True)
class TokenizerInspection:
    tokenizer_type: str | None
    status: str
    vocabulary_present: bool | None
    vocabulary_size: int | None
    special_tokens: Mapping[str, int | tuple[int, ...]]
    add_bos_token: bool | None
    add_eos_token: bool | None
    padding_token_id: int | None
    token_types_present: bool | None
    merges_present: bool | None
    merges_count: int | None
    configuration: Mapping[str, JSONValue]
    unknowns: tuple[str, ...]
    evidence: tuple[EvidenceRecord, ...]


@dataclass(slots=True)
class GenericTokenizerInspector:
    clock: callable = utc_now
    inspector_id: str = "mie.inspector.tokenizer-metadata"
    inspector_version: str = "0.3.0"

    def inspect(
        self,
        *,
        artifact: SubjectRef,
        metadata: Mapping[str, GGUFMetadataValue],
        source_uri: str,
        source_digest: str,
    ) -> TokenizerInspection:
        factory = EvidenceFactory(self.inspector_id, self.inspector_version, self.clock)
        evidence: list[EvidenceRecord] = []

        def record(key: str, value: JSONValue) -> None:
            evidence.append(
                factory.create(
                    kind=EvidenceKind.METADATA_FIELD,
                    level=EvidenceLevel.DETECTED_FROM_METADATA,
                    subject=artifact,
                    observation_key=key,
                    observed_value=value,
                    source_uri=source_uri,
                    source_digest=source_digest,
                    locator=f"/metadata/{key}",
                    outcome=EvidenceOutcome.NOT_APPLICABLE,
                )
            )

        tokenizer_type = _string(metadata, "tokenizer.ggml.model") or _string(
            metadata, "tokenizer.model"
        )
        if tokenizer_type is not None:
            record("tokenizer.type", tokenizer_type)

        tokens = _array(metadata, "tokenizer.ggml.tokens")
        vocabulary_present = tokens is not None if "tokenizer.ggml.tokens" in metadata else None
        vocabulary_size = tokens.count if tokens is not None else None
        if tokens is not None:
            record(
                "tokenizer.vocabulary",
                {
                    "present": True,
                    "size": tokens.count,
                    "element_type": tokens.element_type,
                },
            )

        special: dict[str, int | tuple[int, ...]] = {}
        for key, wrapped in sorted(metadata.items()):
            if key.startswith("tokenizer.") and (
                key.endswith("_token_id") or key.endswith("_token_ids")
            ):
                if isinstance(wrapped.value, int) and not isinstance(wrapped.value, bool):
                    special[key] = wrapped.value
                    record(key, wrapped.value)
                elif isinstance(wrapped.value, GGUFArray) and wrapped.value.values is not None:
                    ids = tuple(
                        item
                        for item in wrapped.value.values
                        if isinstance(item, int) and not isinstance(item, bool)
                    )
                    if len(ids) == wrapped.value.count:
                        special[key] = ids
                        record(key, list(ids))

        add_bos = _bool(metadata, "tokenizer.ggml.add_bos_token")
        add_eos = _bool(metadata, "tokenizer.ggml.add_eos_token")
        padding = _int(metadata, "tokenizer.ggml.padding_token_id")
        for key, value in (
            ("tokenizer.ggml.add_bos_token", add_bos),
            ("tokenizer.ggml.add_eos_token", add_eos),
            ("tokenizer.ggml.padding_token_id", padding),
        ):
            if value is not None:
                record(key, value)

        token_types = _array(metadata, "tokenizer.ggml.token_type")
        token_types_present = token_types is not None if "tokenizer.ggml.token_type" in metadata else None
        if token_types is not None:
            record("tokenizer.token_types", {"present": True, "count": token_types.count})
        merges = _array(metadata, "tokenizer.ggml.merges")
        merges_present = merges is not None if "tokenizer.ggml.merges" in metadata else None
        if merges is not None:
            record("tokenizer.merges", {"present": True, "count": merges.count})

        configuration = {}
        for key in sorted(metadata):
            if key.startswith("tokenizer.") and key not in special:
                value = metadata[key].value
                if isinstance(value, (str, int, float, bool)):
                    configuration[key] = value
                elif isinstance(value, GGUFArray):
                    configuration[key] = {
                        "element_type": value.element_type,
                        "count": value.count,
                    }

        unknowns = []
        for name, value in (
            ("tokenizer_type", tokenizer_type),
            ("vocabulary_presence", vocabulary_present),
            ("vocabulary_size", vocabulary_size),
            ("bos_behavior", add_bos),
            ("eos_behavior", add_eos),
            ("padding_token", padding),
            ("token_types", token_types_present),
            ("merges", merges_present),
        ):
            if value is None:
                unknowns.append(name)
        status = "DETECTED_FROM_METADATA" if tokenizer_type is not None else "UNKNOWN"
        return TokenizerInspection(
            tokenizer_type=tokenizer_type,
            status=status,
            vocabulary_present=vocabulary_present,
            vocabulary_size=vocabulary_size,
            special_tokens=special,
            add_bos_token=add_bos,
            add_eos_token=add_eos,
            padding_token_id=padding,
            token_types_present=token_types_present,
            merges_present=merges_present,
            merges_count=merges.count if merges else None,
            configuration=configuration,
            unknowns=tuple(unknowns),
            evidence=tuple(evidence),
        )


def _value(metadata, key):
    wrapped = metadata.get(key)
    return wrapped.value if wrapped else None


def _string(metadata, key):
    value = _value(metadata, key)
    return value if isinstance(value, str) else None


def _int(metadata, key):
    value = _value(metadata, key)
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _bool(metadata, key):
    value = _value(metadata, key)
    return value if isinstance(value, bool) else None


def _array(metadata, key):
    value = _value(metadata, key)
    return value if isinstance(value, GGUFArray) else None
