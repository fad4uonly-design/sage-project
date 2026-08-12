from __future__ import annotations

import json
import struct
from pathlib import Path


def write_gguf(
    path: Path,
    *,
    architecture: str = "mystery",
    include_tokenizer: bool = True,
    include_template: bool = True,
    extra_metadata: dict | None = None,
    tensors: list[tuple[str, tuple[int, ...], int, int]] | None = None,
) -> Path:
    metadata = {
        "general.architecture": architecture,
        "general.name": "Fixture Generic Model",
        "general.version": "1.0",
        "general.file_type": 15,
        "general.parameter_count": 256,
        "general.alignment": 32,
        f"{architecture}.context_length": 32768,
        f"{architecture}.embedding_length": 8,
        f"{architecture}.block_count": 1,
        f"{architecture}.feed_forward_length": 32,
        f"{architecture}.attention.head_count": 2,
        f"{architecture}.attention.head_count_kv": 1,
        f"{architecture}.custom_future_field": "preserve-me",
    }
    if include_tokenizer:
        metadata.update(
            {
                "tokenizer.ggml.model": "gpt2",
                "tokenizer.ggml.tokens": ["<pad>", "<bos>", "<eos>", "hello"],
                "tokenizer.ggml.merges": ["h e", "he llo"],
                "tokenizer.ggml.token_type": [3, 3, 3, 1],
                "tokenizer.ggml.bos_token_id": 1,
                "tokenizer.ggml.eos_token_id": 2,
                "tokenizer.ggml.padding_token_id": 0,
                "tokenizer.ggml.add_bos_token": True,
                "tokenizer.ggml.add_eos_token": False,
            }
        )
    if include_template:
        metadata["tokenizer.chat_template"] = (
            "{% for message in messages %}{{ message['role'] }}: "
            "{{ message['content'] }}{% endfor %}"
            "{% if tools %}tool_calls function{% endif %}"
        )
    if extra_metadata:
        metadata.update(extra_metadata)
    tensors = tensors or [
        ("token_embd.weight", (16, 8), 12, 0),
        ("blk.0.attn_q.weight", (8, 8), 12, 256),
        ("output.weight", (8, 16), 1, 512),
    ]
    header = bytearray()
    header += b"GGUF"
    header += struct.pack("<IQQ", 3, len(tensors), len(metadata))
    for key, value in metadata.items():
        header += _string(key)
        header += _metadata_value(value)
    for name, dimensions, data_type, offset in tensors:
        header += _string(name)
        header += struct.pack("<I", len(dimensions))
        for dimension in dimensions:
            header += struct.pack("<Q", dimension)
        header += struct.pack("<IQ", data_type, offset)
    while len(header) % 32:
        header.append(0)
    header += b"\0" * 2048
    path.write_bytes(header)
    return path


def _string(value: str) -> bytes:
    data = value.encode("utf-8")
    return struct.pack("<Q", len(data)) + data


def _metadata_value(value) -> bytes:
    if isinstance(value, bool):
        return struct.pack("<I", 7) + struct.pack("<B", int(value))
    if isinstance(value, str):
        return struct.pack("<I", 8) + _string(value)
    if isinstance(value, int):
        return struct.pack("<I", 4) + struct.pack("<I", value)
    if isinstance(value, float):
        return struct.pack("<I", 6) + struct.pack("<f", value)
    if isinstance(value, list):
        if not value:
            element_type = 8
        elif isinstance(value[0], str):
            element_type = 8
        elif isinstance(value[0], int):
            element_type = 4
        else:
            raise TypeError("unsupported fixture array")
        data = struct.pack("<IIQ", 9, element_type, len(value))
        for item in value:
            if element_type == 8:
                data += _string(item)
            else:
                data += struct.pack("<I", item)
        return data
    raise TypeError(f"unsupported fixture value: {type(value)}")


def probe_artifact_document(plan, run_id: str, outcomes: dict[str, str] | None = None):
    outcomes = outcomes or {}
    return {
        "schema_version": "0.3.0",
        "plan_id": plan.plan_id,
        "run_id": run_id,
        "results": [
            {
                "probe_id": case.probe_id,
                "kind": case.kind.value,
                "subject": {
                    "kind": case.subject.kind.value,
                    "subject_id": case.subject.subject_id,
                    "version": case.subject.version,
                    "digest": case.subject.digest,
                },
                "outcome": outcomes.get(case.probe_id, "PASS"),
                "assertions": {"unambiguous": True},
                "measurements": {},
                "output_digest": "sha256:" + "a" * 64,
                "error_code": None,
                "error_message": None,
            }
            for case in plan.cases
        ],
    }
