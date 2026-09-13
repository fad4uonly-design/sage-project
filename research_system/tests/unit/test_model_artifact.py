from dataclasses import FrozenInstanceError

import pytest
from sage_research.domain.model_artifact import (
    LoadOptions,
    ModelArtifact,
    ModelFormat,
    ModelIdentity,
)


def test_identity_slug():
    identity = ModelIdentity(
        family="pythia", name="pythia-70m", version="default", source="huggingface:EleutherAI/pythia-70m"
    )
    assert identity.slug == "pythia/pythia-70m@default"


def test_artifact_to_identity():
    artifact = ModelArtifact(name="pythia-70m")
    identity = artifact.to_identity()
    assert identity.family == "pythia"
    assert identity.name == "pythia-70m"
    assert identity.source == "huggingface:EleutherAI/pythia-70m"


def test_artifact_defaults():
    artifact = ModelArtifact(name="pythia-70m")
    assert artifact.format == ModelFormat.ORIGINAL
    assert artifact.checksum is None


def test_identity_round_trip():
    identity = ModelIdentity(
        family="pythia", name="pythia-70m", version="step143000", source="local:/models/pythia"
    )
    assert ModelIdentity.from_dict(identity.to_dict()) == identity


def test_artifact_round_trip():
    artifact = ModelArtifact(
        name="pythia-70m", version="step143000", source="huggingface:EleutherAI/pythia-70m", checksum="sha256:abc"
    )
    assert ModelArtifact.from_dict(artifact.to_dict()) == artifact


def test_values_are_immutable():
    identity = ModelIdentity(family="p", name="n", version="v", source="s")
    with pytest.raises(FrozenInstanceError):
        identity.family = "q"  # type: ignore[misc]


def test_load_options_are_immutable_and_runtime_agnostic():
    options = LoadOptions(revision="step143000")
    assert options.device == "cpu"
    with pytest.raises(FrozenInstanceError):
        options.revision = "other"  # type: ignore[misc]
