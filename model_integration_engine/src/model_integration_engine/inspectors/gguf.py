"""Bounded, model-agnostic GGUF header/metadata/tensor-table inspection."""

from __future__ import annotations

import hashlib
import math
import struct
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO, Protocol

from ..domain import (
    Completeness,
    EvidenceKind,
    EvidenceLevel,
    EvidenceOutcome,
    EvidenceRecord,
    InspectionFinding,
    InspectionReport,
    JSONValue,
    SubjectKind,
    SubjectRef,
)
from ..evidence import EvidenceFactory, deterministic_id, sha256_digest, utc_now


class GGUFInspectionError(RuntimeError):
    def __init__(self, code: str, message: str, *, offset: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.offset = offset


@dataclass(frozen=True, slots=True)
class GGUFArray:
    element_type: str
    count: int
    values: tuple[object, ...] | None
    materialized_count: int


@dataclass(frozen=True, slots=True)
class GGUFMetadataValue:
    type_name: str
    value: object


@dataclass(frozen=True, slots=True)
class TensorObservation:
    name: str
    dimensions: tuple[int, ...]
    data_type_code: int
    data_type: str
    offset: int
    element_count: int
    quantized: bool


@dataclass(frozen=True, slots=True)
class ObservedGGUF:
    file_digest: str
    file_size: int
    version: int
    tensor_count: int
    metadata_count: int
    metadata: Mapping[str, GGUFMetadataValue]
    tensors: tuple[TensorObservation, ...]
    tensor_data_offset: int
    tensor_type_counts: Mapping[str, int]
    structural_issues: tuple[str, ...]
    unknown_metadata_keys: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class InterpretedGGUF:
    architecture: str | None
    model_identity: Mapping[str, JSONValue]
    parameter_count_declared: int | None
    parameter_count_estimate: int | None
    quantization_declared: str | None
    quantization_observed: tuple[str, ...]
    context_length: int | None
    embedding_length: int | None
    attention: Mapping[str, JSONValue]
    layer_count: int | None
    feed_forward: Mapping[str, JSONValue]
    architecture_extensions: Mapping[str, JSONValue]


@dataclass(frozen=True, slots=True)
class GGUFInspectionResult:
    artifact: SubjectRef
    observed: ObservedGGUF
    interpreted: InterpretedGGUF
    report: InspectionReport
    evidence: tuple[EvidenceRecord, ...]


class ArchitectureMetadataPlugin(Protocol):
    plugin_id: str
    plugin_version: str

    def supports(self, architecture: str) -> bool: ...

    def interpret(
        self,
        metadata: Mapping[str, GGUFMetadataValue],
        tensors: tuple[TensorObservation, ...],
    ) -> Mapping[str, JSONValue]: ...


@dataclass(slots=True)
class ArchitecturePluginRegistry:
    plugins: list[ArchitectureMetadataPlugin] = field(default_factory=list)

    def register(self, plugin: ArchitectureMetadataPlugin) -> None:
        if any(item.plugin_id == plugin.plugin_id for item in self.plugins):
            raise ValueError(f"duplicate architecture plugin: {plugin.plugin_id}")
        self.plugins.append(plugin)

    def interpret(
        self,
        architecture: str | None,
        metadata: Mapping[str, GGUFMetadataValue],
        tensors: tuple[TensorObservation, ...],
    ) -> Mapping[str, JSONValue]:
        if architecture is None:
            return {}
        matches = [item for item in self.plugins if item.supports(architecture)]
        if len(matches) > 1:
            raise GGUFInspectionError(
                "ARCHITECTURE_PLUGIN_AMBIGUOUS",
                f"Multiple plugins claim architecture {architecture}",
            )
        return dict(matches[0].interpret(metadata, tensors)) if matches else {}


@dataclass(frozen=True, slots=True)
class GGUFInspectionLimits:
    max_tensors: int = 1_000_000
    max_metadata: int = 1_000_000
    max_string_bytes: int = 64 * 1024 * 1024
    max_array_items: int = 10_000_000
    max_materialized_array_items: int = 4096
    max_header_bytes: int = 512 * 1024 * 1024
    max_dimensions: int = 8


_VALUE_TYPES = {
    0: ("UINT8", "<B"),
    1: ("INT8", "<b"),
    2: ("UINT16", "<H"),
    3: ("INT16", "<h"),
    4: ("UINT32", "<I"),
    5: ("INT32", "<i"),
    6: ("FLOAT32", "<f"),
    7: ("BOOL", "<B"),
    8: ("STRING", None),
    9: ("ARRAY", None),
    10: ("UINT64", "<Q"),
    11: ("INT64", "<q"),
    12: ("FLOAT64", "<d"),
}

_GGML_TYPES = {
    0: "F32", 1: "F16", 2: "Q4_0", 3: "Q4_1", 6: "Q5_0", 7: "Q5_1",
    8: "Q8_0", 9: "Q8_1", 10: "Q2_K", 11: "Q3_K", 12: "Q4_K",
    13: "Q5_K", 14: "Q6_K", 15: "Q8_K", 16: "IQ2_XXS", 17: "IQ2_XS",
    18: "IQ3_XXS", 19: "IQ1_S", 20: "IQ4_NL", 21: "IQ3_S", 22: "IQ2_S",
    23: "IQ4_XS", 24: "I8", 25: "I16", 26: "I32", 27: "I64", 28: "F64",
    29: "IQ1_M", 30: "BF16", 31: "TQ1_0", 32: "TQ2_0", 33: "MXFP4",
}

_FILE_TYPES = {
    0: "ALL_F32", 1: "MOSTLY_F16", 2: "MOSTLY_Q4_0", 3: "MOSTLY_Q4_1",
    6: "MOSTLY_Q5_0", 7: "MOSTLY_Q5_1", 8: "MOSTLY_Q8_0", 10: "MOSTLY_Q2_K",
    11: "MOSTLY_Q3_K_S", 12: "MOSTLY_Q3_K_M", 13: "MOSTLY_Q3_K_L",
    14: "MOSTLY_Q4_K_S", 15: "MOSTLY_Q4_K_M", 16: "MOSTLY_Q5_K_S",
    17: "MOSTLY_Q5_K_M", 18: "MOSTLY_Q6_K",
}


class _Reader:
    def __init__(self, handle: BinaryIO, limits: GGUFInspectionLimits) -> None:
        self.handle = handle
        self.limits = limits
        self.offset = 0

    def read(self, count: int) -> bytes:
        if count < 0 or self.offset + count > self.limits.max_header_bytes:
            raise GGUFInspectionError(
                "GGUF_HEADER_LIMIT_EXCEEDED", "GGUF header exceeds configured limit", offset=self.offset
            )
        value = self.handle.read(count)
        if len(value) != count:
            raise GGUFInspectionError(
                "GGUF_TRUNCATED", "Unexpected end of GGUF header", offset=self.offset
            )
        self.offset += count
        return value

    def unpack(self, fmt: str):
        size = struct.calcsize(fmt)
        return struct.unpack(fmt, self.read(size))[0]

    def string(self) -> str:
        length = self.unpack("<Q")
        if length > self.limits.max_string_bytes:
            raise GGUFInspectionError(
                "GGUF_STRING_LIMIT_EXCEEDED", f"String length {length} exceeds limit", offset=self.offset
            )
        raw = self.read(length)
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise GGUFInspectionError(
                "GGUF_INVALID_UTF8", "GGUF string is not UTF-8", offset=self.offset - length
            ) from exc

    def value(self, value_type: int, *, materialize: bool = True):
        descriptor = _VALUE_TYPES.get(value_type)
        if descriptor is None:
            raise GGUFInspectionError(
                "GGUF_VALUE_TYPE_UNSUPPORTED", f"Unknown GGUF value type {value_type}", offset=self.offset
            )
        name, fmt = descriptor
        if fmt is not None:
            value = self.unpack(fmt)
            if name == "BOOL":
                if value not in (0, 1):
                    raise GGUFInspectionError("GGUF_BOOL_INVALID", "Boolean value must be 0 or 1")
                value = bool(value)
            return GGUFMetadataValue(name, value)
        if name == "STRING":
            return GGUFMetadataValue(name, self.string())
        element_type = self.unpack("<I")
        count = self.unpack("<Q")
        if count > self.limits.max_array_items:
            raise GGUFInspectionError(
                "GGUF_ARRAY_LIMIT_EXCEEDED", f"Array count {count} exceeds limit", offset=self.offset
            )
        if element_type == 9:
            raise GGUFInspectionError("GGUF_NESTED_ARRAY_UNSUPPORTED", "Nested GGUF arrays are invalid")
        element_descriptor = _VALUE_TYPES.get(element_type)
        if element_descriptor is None:
            raise GGUFInspectionError(
                "GGUF_VALUE_TYPE_UNSUPPORTED", f"Unknown array type {element_type}", offset=self.offset
            )
        values: list[object] = []
        materialized = min(count, self.limits.max_materialized_array_items)
        for index in range(count):
            child = self.value(element_type, materialize=index < materialized)
            if index < materialized:
                values.append(child.value)
        array = GGUFArray(
            element_type=element_descriptor[0],
            count=count,
            values=tuple(values) if count <= self.limits.max_materialized_array_items else tuple(values),
            materialized_count=len(values),
        )
        return GGUFMetadataValue("ARRAY", array)


@dataclass(slots=True)
class GGUFInspector:
    limits: GGUFInspectionLimits = field(default_factory=GGUFInspectionLimits)
    architecture_plugins: ArchitecturePluginRegistry = field(default_factory=ArchitecturePluginRegistry)
    clock: callable = utc_now
    inspector_id: str = "mie.inspector.gguf"
    inspector_version: str = "0.3.0"

    def inspect(self, path: Path, *, expected_digest: str | None = None) -> GGUFInspectionResult:
        path = path.resolve()
        if path.is_symlink() or not path.is_file():
            raise GGUFInspectionError("GGUF_PATH_INVALID", "GGUF path must be a regular file")
        file_size = path.stat().st_size
        file_digest = _hash_file(path)
        if expected_digest and file_digest != expected_digest:
            raise GGUFInspectionError("GGUF_DIGEST_MISMATCH", "GGUF content digest mismatch")
        artifact = SubjectRef(
            SubjectKind.ARTIFACT,
            deterministic_id("artifact:gguf", file_digest),
            digest=file_digest,
        )
        with path.open("rb") as handle:
            reader = _Reader(handle, self.limits)
            if reader.read(4) != b"GGUF":
                raise GGUFInspectionError("GGUF_MAGIC_INVALID", "File does not start with GGUF magic", offset=0)
            version = reader.unpack("<I")
            if version not in {2, 3}:
                raise GGUFInspectionError(
                    "GGUF_VERSION_UNSUPPORTED", f"Unsupported GGUF version {version}", offset=4
                )
            tensor_count = reader.unpack("<Q")
            metadata_count = reader.unpack("<Q")
            if tensor_count > self.limits.max_tensors or metadata_count > self.limits.max_metadata:
                raise GGUFInspectionError("GGUF_COUNT_LIMIT_EXCEEDED", "GGUF counts exceed configured limits")

            metadata: dict[str, GGUFMetadataValue] = {}
            duplicate_metadata = []
            for _ in range(metadata_count):
                key = reader.string()
                value_type = reader.unpack("<I")
                value = reader.value(value_type)
                if key in metadata:
                    duplicate_metadata.append(key)
                metadata[key] = value

            tensors: list[TensorObservation] = []
            tensor_names: set[str] = set()
            issues = [f"duplicate metadata key: {key}" for key in duplicate_metadata]
            for _ in range(tensor_count):
                name = reader.string()
                dimensions_count = reader.unpack("<I")
                if dimensions_count == 0 or dimensions_count > self.limits.max_dimensions:
                    raise GGUFInspectionError(
                        "GGUF_TENSOR_DIMENSIONS_INVALID",
                        f"Tensor {name!r} dimension count is invalid",
                        offset=reader.offset,
                    )
                dimensions = tuple(reader.unpack("<Q") for _ in range(dimensions_count))
                data_type_code = reader.unpack("<I")
                offset = reader.unpack("<Q")
                data_type = _GGML_TYPES.get(data_type_code, f"GGML_TYPE_{data_type_code}")
                element_count = math.prod(dimensions)
                if name in tensor_names:
                    issues.append(f"duplicate tensor name: {name}")
                tensor_names.add(name)
                if any(size == 0 for size in dimensions):
                    issues.append(f"zero-sized tensor dimension: {name}")
                tensors.append(
                    TensorObservation(
                        name=name,
                        dimensions=dimensions,
                        data_type_code=data_type_code,
                        data_type=data_type,
                        offset=offset,
                        element_count=element_count,
                        quantized=data_type.startswith(("Q", "IQ", "TQ", "MX")),
                    )
                )
            alignment_value = _metadata_scalar(metadata, "general.alignment")
            alignment = alignment_value if isinstance(alignment_value, int) and alignment_value >= 8 else 32
            tensor_data_offset = ((reader.offset + alignment - 1) // alignment) * alignment
            for tensor in tensors:
                if tensor_data_offset + tensor.offset >= file_size:
                    issues.append(f"tensor offset outside file: {tensor.name}")
            if tensor_count != len(tensors):
                issues.append("tensor count mismatch")

        tensor_type_counts = dict(sorted(Counter(item.data_type for item in tensors).items()))
        observed = ObservedGGUF(
            file_digest=file_digest,
            file_size=file_size,
            version=version,
            tensor_count=tensor_count,
            metadata_count=metadata_count,
            metadata=metadata,
            tensors=tuple(tensors),
            tensor_data_offset=tensor_data_offset,
            tensor_type_counts=tensor_type_counts,
            structural_issues=tuple(issues),
            unknown_metadata_keys=tuple(sorted(metadata)),
        )
        interpreted = self._interpret(observed)
        evidence, report = self._evidence(path, artifact, observed, interpreted)
        return GGUFInspectionResult(
            artifact=artifact,
            observed=observed,
            interpreted=interpreted,
            report=report,
            evidence=evidence,
        )

    def _interpret(self, observed: ObservedGGUF) -> InterpretedGGUF:
        metadata = observed.metadata
        architecture_value = _metadata_scalar(metadata, "general.architecture")
        architecture = architecture_value if isinstance(architecture_value, str) else None
        identity_keys = (
            "general.name", "general.basename", "general.author", "general.organization",
            "general.version", "general.finetune", "general.uuid", "general.repo_url",
            "general.source.repo_url",
        )
        identity = {
            key: value
            for key in identity_keys
            if (value := _json_scalar(_metadata_scalar(metadata, key))) is not None
        }
        declared_parameters = _first_int(
            metadata,
            ("general.parameter_count", "general.size_label.parameter_count"),
        )
        parameter_estimate = sum(item.element_count for item in observed.tensors) or None
        file_type = _metadata_scalar(metadata, "general.file_type")
        quantization_declared = _FILE_TYPES.get(file_type, str(file_type)) if isinstance(file_type, int) else None
        quantization_observed = tuple(
            sorted(name for name in observed.tensor_type_counts if name.startswith(("Q", "IQ", "TQ", "MX")))
        )

        prefix = f"{architecture}." if architecture else None
        context = _int_at(metadata, prefix + "context_length") if prefix else None
        embedding = _int_at(metadata, prefix + "embedding_length") if prefix else None
        layers = _int_at(metadata, prefix + "block_count") if prefix else None
        attention = {}
        feed_forward = {}
        if prefix:
            for key, wrapped in metadata.items():
                if key.startswith(prefix + "attention."):
                    attention[key.removeprefix(prefix)] = _json_value(wrapped.value)
                if key.startswith(prefix + "feed_forward") or key.startswith(prefix + "expert"):
                    feed_forward[key.removeprefix(prefix)] = _json_value(wrapped.value)
            ff_length = _metadata_scalar(metadata, prefix + "feed_forward_length")
            if ff_length is not None:
                feed_forward["feed_forward_length"] = _json_value(ff_length)
        extensions = self.architecture_plugins.interpret(architecture, metadata, observed.tensors)
        return InterpretedGGUF(
            architecture=architecture,
            model_identity=identity,
            parameter_count_declared=declared_parameters,
            parameter_count_estimate=parameter_estimate,
            quantization_declared=quantization_declared,
            quantization_observed=quantization_observed,
            context_length=context,
            embedding_length=embedding,
            attention=attention,
            layer_count=layers,
            feed_forward=feed_forward,
            architecture_extensions=extensions,
        )

    def _evidence(self, path, artifact, observed, interpreted):
        factory = EvidenceFactory(self.inspector_id, self.inspector_version, self.clock)
        evidence: list[EvidenceRecord] = []
        findings: list[InspectionFinding] = []
        source_uri = path.as_uri()

        def fact(key: str, value: JSONValue, locator: str, level=EvidenceLevel.DETECTED_FROM_METADATA):
            item = factory.create(
                kind=EvidenceKind.METADATA_FIELD,
                level=level,
                subject=artifact,
                observation_key=key,
                observed_value=value,
                source_uri=source_uri,
                source_digest=observed.file_digest,
                locator=locator,
                outcome=EvidenceOutcome.NOT_APPLICABLE,
            )
            evidence.append(item)
            findings.append(
                InspectionFinding(
                    path=key,
                    raw_value=value,
                    normalized_value=value,
                    value_type=type(value).__name__,
                    source=item.source,
                    evidence_level=item.level,
                    evidence_id=item.evidence_id,
                )
            )
            return item

        fact("gguf.version", observed.version, "/header/version")
        tensor_ev = fact(
            "gguf.tensor_structure",
            {
                "count": observed.tensor_count,
                "type_counts": dict(observed.tensor_type_counts),
                "shape_manifest_digest": sha256_digest(
                    [{"name": item.name, "shape": list(item.dimensions), "type": item.data_type} for item in observed.tensors]
                ),
                "structural_issues": list(observed.structural_issues),
            },
            "/tensor_info",
        )
        fact("gguf.metadata_count", observed.metadata_count, "/header/metadata_count")
        for key in (
            "general.architecture", "general.name", "general.basename", "general.version",
            "general.file_type", "general.parameter_count",
        ):
            if key in observed.metadata:
                fact(key, _json_value(observed.metadata[key].value), f"/metadata/{key}")
        if interpreted.architecture:
            prefix = interpreted.architecture
            for key in (
                f"{prefix}.context_length", f"{prefix}.embedding_length",
                f"{prefix}.block_count", f"{prefix}.feed_forward_length",
                f"{prefix}.attention.head_count", f"{prefix}.attention.head_count_kv",
            ):
                if key in observed.metadata:
                    fact(key, _json_value(observed.metadata[key].value), f"/metadata/{key}")
        for key in sorted(observed.metadata):
            if key.startswith("tokenizer.") and key not in {item.observation_key for item in evidence}:
                value = observed.metadata[key].value
                summarized = _summarize_metadata_value(value)
                fact(key, summarized, f"/metadata/{key}")

        if interpreted.parameter_count_estimate is not None:
            derived = factory.create(
                kind=EvidenceKind.DERIVATION,
                level=EvidenceLevel.INFERRED,
                subject=artifact,
                observation_key="derived.parameter_count_estimate",
                observed_value={
                    "estimate": interpreted.parameter_count_estimate,
                    "method": "sum_tensor_shape_elements",
                },
                source_uri="urn:mie:derivation:gguf-tensor-elements-v1",
                source_digest=sha256_digest({"method": "sum_tensor_shape_elements", "version": 1}),
                locator="sum_tensor_shape_elements",
                outcome=EvidenceOutcome.NOT_APPLICABLE,
                derived_from=(tensor_ev.evidence_id,),
            )
            evidence.append(derived)
        report = InspectionReport(
            report_id=deterministic_id("inspection:gguf", observed.file_digest, self.inspector_version),
            inspector_id=self.inspector_id,
            inspector_version=self.inspector_version,
            subject=artifact,
            requested_levels=("IDENTITY_ONLY", "METADATA", "STRUCTURE", "TOKENIZER", "TEMPLATE"),
            completed_levels=("IDENTITY_ONLY", "METADATA", "STRUCTURE", "TOKENIZER", "TEMPLATE"),
            findings=tuple(findings),
            unknown_fields={
                key: _summarize_metadata_value(observed.metadata[key].value)
                for key in observed.unknown_metadata_keys
                if not key.startswith(("general.", "tokenizer.", (interpreted.architecture or "__none__") + "."))
            },
            contradictions=observed.structural_issues,
            completeness=Completeness.COMPLETE if not observed.structural_issues else Completeness.PARTIAL,
            evidence_ids=tuple(item.evidence_id for item in evidence),
        )
        return tuple(evidence), report


def _metadata_scalar(metadata, key):
    wrapped = metadata.get(key)
    if wrapped is None or isinstance(wrapped.value, GGUFArray):
        return None
    return wrapped.value


def _int_at(metadata, key):
    value = _metadata_scalar(metadata, key)
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _first_int(metadata, keys):
    for key in keys:
        value = _int_at(metadata, key)
        if value is not None:
            return value
    return None


def _json_scalar(value):
    return value if value is None or isinstance(value, (str, int, float, bool)) else None


def _json_value(value) -> JSONValue:
    if isinstance(value, GGUFArray):
        return {
            "element_type": value.element_type,
            "count": value.count,
            "materialized_count": value.materialized_count,
            "values": [_json_value(item) for item in (value.values or ())],
        }
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    return str(value)


def _summarize_metadata_value(value) -> JSONValue:
    if isinstance(value, GGUFArray):
        result = {
            "element_type": value.element_type,
            "count": value.count,
            "materialized_count": value.materialized_count,
        }
        if value.values is not None and value.count <= 64:
            result["values"] = [_json_value(item) for item in value.values]
        return result
    if isinstance(value, str) and len(value) > 4096:
        return {"length": len(value), "digest": sha256_digest(value.encode("utf-8"))}
    return _json_value(value)


def _hash_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            hasher.update(chunk)
    return "sha256:" + hasher.hexdigest()
