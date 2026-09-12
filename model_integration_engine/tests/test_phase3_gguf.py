from __future__ import annotations

import struct

import pytest
from model_integration_engine.domain import EvidenceLevel
from model_integration_engine.inspectors.gguf import (
    GGUFInspectionError,
    GGUFInspector,
)
from model_integration_engine.inspectors.template import GenericChatTemplateInspector
from model_integration_engine.inspectors.tokenizer import GenericTokenizerInspector

from tests.phase2_support import fixed_clock
from tests.phase3_support import write_gguf


def test_generic_gguf_inspection_handles_unknown_architecture(tmp_path) -> None:
    path = write_gguf(tmp_path / "unknown.gguf", architecture="futurearch")
    result = GGUFInspector(clock=fixed_clock).inspect(path)

    assert result.observed.version == 3
    assert result.observed.tensor_count == 3
    assert result.observed.metadata_count >= 10
    assert result.interpreted.architecture == "futurearch"
    assert result.interpreted.context_length == 32768
    assert result.interpreted.embedding_length == 8
    assert result.interpreted.layer_count == 1
    assert result.interpreted.attention["attention.head_count"] == 2
    assert result.interpreted.feed_forward["feed_forward_length"] == 32
    assert result.interpreted.architecture_extensions == {}
    assert result.report.completeness.value == "COMPLETE"


def test_tensor_inspection_separates_observed_from_interpreted(tmp_path) -> None:
    result = GGUFInspector(clock=fixed_clock).inspect(write_gguf(tmp_path / "tensors.gguf"))

    assert [item.name for item in result.observed.tensors] == [
        "token_embd.weight",
        "blk.0.attn_q.weight",
        "output.weight",
    ]
    assert result.observed.tensors[0].dimensions == (16, 8)
    assert result.observed.tensors[0].data_type == "Q4_K"
    assert result.observed.tensors[0].quantized is True
    assert result.observed.tensor_type_counts == {"F16": 1, "Q4_K": 2}
    assert result.interpreted.parameter_count_declared == 256
    assert result.interpreted.parameter_count_estimate == 320
    derived = next(
        item
        for item in result.evidence
        if item.observation_key == "derived.parameter_count_estimate"
    )
    assert derived.level is EvidenceLevel.INFERRED
    assert derived.derived_from


def test_unknown_tensor_type_is_observed_without_crash(tmp_path) -> None:
    path = write_gguf(
        tmp_path / "future-type.gguf",
        tensors=[("future.weight", (4, 4), 999, 0)],
    )
    result = GGUFInspector(clock=fixed_clock).inspect(path)
    assert result.observed.tensors[0].data_type == "GGML_TYPE_999"
    assert result.observed.tensors[0].quantized is False


def test_unknown_metadata_is_preserved(tmp_path) -> None:
    result = GGUFInspector(clock=fixed_clock).inspect(
        write_gguf(
            tmp_path / "metadata.gguf",
            extra_metadata={"vendor.future.setting": "opaque-value"},
        )
    )
    assert result.observed.metadata["vendor.future.setting"].value == "opaque-value"
    assert result.report.unknown_fields["vendor.future.setting"] == "opaque-value"


@pytest.mark.parametrize(
    "payload,code",
    [
        (b"NOPE" + b"\0" * 40, "GGUF_MAGIC_INVALID"),
        (b"GGUF" + struct.pack("<I", 3), "GGUF_TRUNCATED"),
        (b"GGUF" + struct.pack("<IQQ", 99, 0, 0), "GGUF_VERSION_UNSUPPORTED"),
    ],
)
def test_corrupted_or_malformed_gguf_fails_structurally(tmp_path, payload, code) -> None:
    path = tmp_path / "corrupt.gguf"
    path.write_bytes(payload)
    with pytest.raises(GGUFInspectionError) as error:
        GGUFInspector().inspect(path)
    assert error.value.code == code


def test_tokenizer_inspection_variations_and_unknown_semantics(tmp_path) -> None:
    full = GGUFInspector(clock=fixed_clock).inspect(write_gguf(tmp_path / "full.gguf"))
    tokenizer = GenericTokenizerInspector(clock=fixed_clock).inspect(
        artifact=full.artifact,
        metadata=full.observed.metadata,
        source_uri=(tmp_path / "full.gguf").as_uri(),
        source_digest=full.observed.file_digest,
    )
    assert tokenizer.tokenizer_type == "gpt2"
    assert tokenizer.vocabulary_present is True
    assert tokenizer.vocabulary_size == 4
    assert tokenizer.special_tokens["tokenizer.ggml.bos_token_id"] == 1
    assert tokenizer.add_bos_token is True
    assert tokenizer.add_eos_token is False
    assert tokenizer.padding_token_id == 0
    assert tokenizer.token_types_present is True
    assert tokenizer.merges_count == 2

    missing_path = write_gguf(
        tmp_path / "missing-tokenizer.gguf", include_tokenizer=False
    )
    missing = GGUFInspector(clock=fixed_clock).inspect(missing_path)
    unknown = GenericTokenizerInspector(clock=fixed_clock).inspect(
        artifact=missing.artifact,
        metadata=missing.observed.metadata,
        source_uri=missing_path.as_uri(),
        source_digest=missing.observed.file_digest,
    )
    assert unknown.status == "UNKNOWN"
    assert unknown.vocabulary_present is None
    assert "tokenizer_type" in unknown.unknowns


def test_chat_template_inspection_is_static_not_behavioral(tmp_path) -> None:
    path = write_gguf(tmp_path / "template.gguf")
    gguf = GGUFInspector(clock=fixed_clock).inspect(path)
    template = GenericChatTemplateInspector(clock=fixed_clock).inspect(
        artifact=gguf.artifact,
        metadata=gguf.observed.metadata,
        source_uri=path.as_uri(),
        source_digest=gguf.observed.file_digest,
    )
    assert template.present is True
    assert template.syntax == "JINJA_LIKE"
    assert {"user", "assistant"}.issubset(set(template.possible_roles)) is False
    # The fixture uses a generic role variable, so literal roles are not invented.
    assert template.tool_syntax_hint is True
    assert template.behavior_validated is False
    assert template.evidence[1].level is EvidenceLevel.INFERRED

    missing_path = write_gguf(
        tmp_path / "missing-template.gguf", include_template=False
    )
    missing = GGUFInspector(clock=fixed_clock).inspect(missing_path)
    unknown = GenericChatTemplateInspector(clock=fixed_clock).inspect(
        artifact=missing.artifact,
        metadata=missing.observed.metadata,
        source_uri=missing_path.as_uri(),
        source_digest=missing.observed.file_digest,
    )
    assert unknown.present is None
    assert unknown.status == "UNKNOWN"
    assert unknown.tool_syntax_hint is None
