"""Content-addressed artifact resolution and typed-ingestion gate."""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from ..evidence import deterministic_id, sha256_digest
from .contracts import ArtifactDeclaration, CollectedArtifactCandidate


class ArtifactResolutionError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class ArtifactProvenance:
    run_id: str
    artifact_id: str
    source_relative_path: str
    source_reported_digest: str
    resolver_id: str
    resolver_version: str


@dataclass(frozen=True, slots=True)
class ResolvedArtifact:
    artifact_id: str
    media_type: str
    digest: str
    size_bytes: int
    store_path: str
    provenance: ArtifactProvenance


@dataclass(frozen=True, slots=True)
class ArtifactResolution:
    artifacts: tuple[ResolvedArtifact, ...]
    manifest_digest: str


class SecureArtifactResolver:
    """Verify sandbox artifacts before they can be used as evidence.

    Files are accepted only when declared, regular, non-symlink, bounded, type
    checked, and digest verified. Accepted bytes are copied into a private
    content-addressed store and reverified on read.
    """

    resolver_id = "mie.artifacts.secure-resolver"
    resolver_version = "0.3.0"

    def __init__(self, store_root: Path) -> None:
        self.store_root = store_root.resolve()
        self.store_root.mkdir(parents=True, exist_ok=True)

    def resolve(
        self,
        *,
        collection_root: Path,
        declarations: tuple[ArtifactDeclaration, ...],
        candidates: tuple[CollectedArtifactCandidate, ...],
        run_id: str,
    ) -> ArtifactResolution:
        root = collection_root.resolve()
        declarations_by_path = {item.relative_path: item for item in declarations}
        if len(declarations_by_path) != len(declarations):
            raise ArtifactResolutionError(
                "DUPLICATE_ARTIFACT_DECLARATION", "Artifact paths must be unique"
            )
        candidates_by_path = {item.relative_path: item for item in candidates}
        if len(candidates_by_path) != len(candidates):
            raise ArtifactResolutionError(
                "DUPLICATE_ARTIFACT_CANDIDATE", "Produced artifact paths must be unique"
            )

        actual_paths: set[str] = set()
        if root.exists():
            for path in root.rglob("*"):
                if path.is_symlink():
                    raise ArtifactResolutionError(
                        "ARTIFACT_SYMLINK_REJECTED", f"Symlink artifact rejected: {path}"
                    )
                if path.is_file():
                    actual_paths.add(path.relative_to(root).as_posix())
        unexpected = actual_paths - set(declarations_by_path)
        if unexpected:
            raise ArtifactResolutionError(
                "UNEXPECTED_ARTIFACT",
                "Unexpected artifact(s): " + ", ".join(sorted(unexpected)),
            )
        undeclared_candidates = set(candidates_by_path) - set(declarations_by_path)
        if undeclared_candidates:
            raise ArtifactResolutionError(
                "UNDECLARED_ARTIFACT_CANDIDATE",
                "Candidate manifest contains undeclared artifact(s)",
            )

        resolved: list[ResolvedArtifact] = []
        for relative_path, declaration in sorted(declarations_by_path.items()):
            candidate = candidates_by_path.get(relative_path)
            path = _safe_child(root, relative_path)
            if not path.exists():
                if declaration.required:
                    raise ArtifactResolutionError(
                        "REQUIRED_ARTIFACT_MISSING", f"Missing {relative_path}"
                    )
                continue
            if candidate is None:
                raise ArtifactResolutionError(
                    "ARTIFACT_MANIFEST_MISSING", f"No candidate record for {relative_path}"
                )
            if candidate.artifact_id != declaration.artifact_id:
                raise ArtifactResolutionError(
                    "ARTIFACT_ID_MISMATCH", f"Artifact ID mismatch for {relative_path}"
                )
            if candidate.media_type != declaration.media_type:
                raise ArtifactResolutionError(
                    "ARTIFACT_TYPE_MISMATCH", f"Artifact type mismatch for {relative_path}"
                )
            if Path(candidate.collection_root).resolve() != root:
                raise ArtifactResolutionError(
                    "ARTIFACT_ROOT_MISMATCH", "Candidate collection root mismatch"
                )
            stat = path.stat(follow_symlinks=False)
            if not path.is_file() or stat.st_size > declaration.max_bytes:
                raise ArtifactResolutionError(
                    "ARTIFACT_SIZE_INVALID", f"Artifact size invalid for {relative_path}"
                )
            digest = _hash_file(path)
            if digest != candidate.reported_digest:
                raise ArtifactResolutionError(
                    "ARTIFACT_DIGEST_MISMATCH", f"Reported digest mismatch for {relative_path}"
                )
            if declaration.expected_digest and digest != declaration.expected_digest:
                raise ArtifactResolutionError(
                    "ARTIFACT_EXPECTED_DIGEST_MISMATCH",
                    f"Expected digest mismatch for {relative_path}",
                )
            _validate_media_type(path, declaration.media_type)
            digest_hex = digest.removeprefix("sha256:")
            destination = self.store_root / digest_hex[:2] / digest_hex
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                if _hash_file(destination) != digest:
                    raise ArtifactResolutionError(
                        "ARTIFACT_STORE_COLLISION", "Content store digest collision"
                    )
            else:
                temporary = destination.with_suffix(".tmp")
                shutil.copyfile(path, temporary)
                os.chmod(temporary, 0o400)
                os.replace(temporary, destination)
            resolved.append(
                ResolvedArtifact(
                    artifact_id=declaration.artifact_id,
                    media_type=declaration.media_type,
                    digest=digest,
                    size_bytes=stat.st_size,
                    store_path=str(destination),
                    provenance=ArtifactProvenance(
                        run_id=run_id,
                        artifact_id=declaration.artifact_id,
                        source_relative_path=relative_path,
                        source_reported_digest=candidate.reported_digest,
                        resolver_id=self.resolver_id,
                        resolver_version=self.resolver_version,
                    ),
                )
            )

        manifest = [
            {
                "artifact_id": item.artifact_id,
                "media_type": item.media_type,
                "digest": item.digest,
                "size_bytes": item.size_bytes,
                "run_id": item.provenance.run_id,
            }
            for item in resolved
        ]
        return ArtifactResolution(
            artifacts=tuple(resolved), manifest_digest=sha256_digest(manifest)
        )

    def read_verified(self, artifact: ResolvedArtifact) -> bytes:
        path = Path(artifact.store_path)
        data = path.read_bytes()
        if sha256_digest(data) != artifact.digest:
            raise ArtifactResolutionError(
                "RESOLVED_ARTIFACT_TAMPERED", f"Stored artifact {artifact.artifact_id} changed"
            )
        return data


def _safe_child(root: Path, relative_path: str) -> Path:
    pure = PurePosixPath(relative_path)
    if pure.is_absolute() or ".." in pure.parts:
        raise ArtifactResolutionError("ARTIFACT_PATH_INVALID", "Invalid artifact path")
    candidate = (root / Path(*pure.parts)).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ArtifactResolutionError(
            "ARTIFACT_PATH_ESCAPE", "Artifact path escapes collection root"
        ) from exc
    return candidate


def _hash_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    import hashlib

    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            hasher.update(chunk)
    return "sha256:" + hasher.hexdigest()


def _validate_media_type(path: Path, media_type: str) -> None:
    if media_type in {
        "application/json",
        "application/vnd.mie.probe-results+json",
        "application/vnd.mie.evidence+json",
    }:
        try:
            value: Any = json.loads(path.read_bytes())
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ArtifactResolutionError(
                "ARTIFACT_TYPE_VALIDATION_FAILED", f"Invalid JSON artifact: {path.name}"
            ) from exc
        if not isinstance(value, (dict, list)):
            raise ArtifactResolutionError(
                "ARTIFACT_TYPE_VALIDATION_FAILED", "JSON artifact must be object or array"
            )
    elif media_type == "application/x-gguf":
        # Read only the identifying bytes. A GGUF artifact may be many
        # gigabytes, so whole-file reads are forbidden at this gate.
        with path.open("rb") as handle:
            magic = handle.read(4)
        if magic != b"GGUF":
            raise ArtifactResolutionError(
                "ARTIFACT_TYPE_VALIDATION_FAILED", "GGUF artifact has wrong magic"
            )
    elif media_type.startswith("text/"):
        try:
            path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise ArtifactResolutionError(
                "ARTIFACT_TYPE_VALIDATION_FAILED", "Text artifact is not UTF-8"
            ) from exc
    elif media_type != "application/octet-stream":
        raise ArtifactResolutionError(
            "ARTIFACT_TYPE_UNSUPPORTED", f"Unsupported declared type: {media_type}"
        )
