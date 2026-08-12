"""Bounded static chat-template inspection.

Static syntax can establish presence and hints only; it never validates model
behavior or reliable tool/structured-output support.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping

from ..domain import (
    EvidenceKind,
    EvidenceLevel,
    EvidenceOutcome,
    EvidenceRecord,
    SubjectRef,
)
from ..evidence import EvidenceFactory, sha256_digest, utc_now
from .gguf import GGUFMetadataValue


@dataclass(frozen=True, slots=True)
class ChatTemplateInspection:
    present: bool | None
    source_key: str | None
    template_digest: str | None
    template_length: int | None
    syntax: str | None
    possible_roles: tuple[str, ...]
    tool_syntax_hint: bool | None
    structured_output_hint: bool | None
    behavior_validated: bool
    status: str
    warnings: tuple[str, ...]
    evidence: tuple[EvidenceRecord, ...]


@dataclass(slots=True)
class GenericChatTemplateInspector:
    max_template_bytes: int = 4 * 1024 * 1024
    clock: callable = utc_now
    inspector_id: str = "mie.inspector.chat-template"
    inspector_version: str = "0.3.0"

    def inspect(
        self,
        *,
        artifact: SubjectRef,
        metadata: Mapping[str, GGUFMetadataValue],
        source_uri: str,
        source_digest: str,
    ) -> ChatTemplateInspection:
        keys = (
            "tokenizer.chat_template",
            "tokenizer.ggml.chat_template",
            "chat_template",
        )
        source_key = next(
            (
                key
                for key in keys
                if key in metadata and isinstance(metadata[key].value, str)
            ),
            None,
        )
        if source_key is None:
            return ChatTemplateInspection(
                present=None,
                source_key=None,
                template_digest=None,
                template_length=None,
                syntax=None,
                possible_roles=(),
                tool_syntax_hint=None,
                structured_output_hint=None,
                behavior_validated=False,
                status="UNKNOWN",
                warnings=("No supported chat-template metadata key was observed.",),
                evidence=(),
            )
        template = metadata[source_key].value
        assert isinstance(template, str)
        encoded = template.encode("utf-8")
        if len(encoded) > self.max_template_bytes:
            return ChatTemplateInspection(
                present=True,
                source_key=source_key,
                template_digest=sha256_digest(encoded),
                template_length=len(template),
                syntax=None,
                possible_roles=(),
                tool_syntax_hint=None,
                structured_output_hint=None,
                behavior_validated=False,
                status="PARTIAL",
                warnings=("Template exceeds static-analysis size limit.",),
                evidence=(),
            )

        syntax = _syntax(template)
        lower = template.lower()
        possible_roles = tuple(
            role
            for role in ("system", "user", "assistant", "tool")
            if re.search(rf"(?<![a-z]){role}(?![a-z])", lower)
        )
        tool_hint = any(
            token in lower
            for token in ("tool_calls", "tool_call", "tools", "function.name", "function_call")
        )
        structured_hint = any(
            token in lower for token in ("json_schema", "response_format", "structured_output")
        )
        factory = EvidenceFactory(self.inspector_id, self.inspector_version, self.clock)
        presence = factory.create(
            kind=EvidenceKind.METADATA_FIELD,
            level=EvidenceLevel.DETECTED_FROM_METADATA,
            subject=artifact,
            observation_key="chat_template.presence",
            observed_value={
                "present": True,
                "source_key": source_key,
                "digest": sha256_digest(encoded),
                "length": len(template),
            },
            source_uri=source_uri,
            source_digest=source_digest,
            locator=f"/metadata/{source_key}",
            outcome=EvidenceOutcome.NOT_APPLICABLE,
        )
        analysis = factory.create(
            kind=EvidenceKind.DERIVATION,
            level=EvidenceLevel.INFERRED,
            subject=artifact,
            observation_key="chat_template.static_analysis",
            observed_value={
                "syntax": syntax,
                "possible_roles": list(possible_roles),
                "tool_syntax_hint": tool_hint,
                "structured_output_hint": structured_hint,
                "behavior_validated": False,
            },
            source_uri="urn:mie:template-static-analysis:v1",
            source_digest=sha256_digest({"rule": "template-static-analysis", "version": 1}),
            locator="static-analysis",
            outcome=EvidenceOutcome.NOT_APPLICABLE,
            derived_from=(presence.evidence_id,),
        )
        return ChatTemplateInspection(
            present=True,
            source_key=source_key,
            template_digest=sha256_digest(encoded),
            template_length=len(template),
            syntax=syntax,
            possible_roles=possible_roles,
            tool_syntax_hint=tool_hint,
            structured_output_hint=structured_hint,
            behavior_validated=False,
            status="DETECTED_FROM_METADATA",
            warnings=(
                "Roles and feature hints are static inferences, not behavioral validation.",
            ),
            evidence=(presence, analysis),
        )


def _syntax(template: str) -> str:
    if "{{" in template and any(token in template for token in (".Messages", ".Role", ".Content")):
        return "GO_TEMPLATE_LIKE"
    if "{%" in template or (
        "{{" in template
        and ("messages" in template.lower() or "raise_exception" in template)
    ):
        return "JINJA_LIKE"
    return "UNKNOWN_TEMPLATE_SYNTAX"
