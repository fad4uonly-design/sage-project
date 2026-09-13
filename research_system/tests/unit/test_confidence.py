import pytest
from sage_research.domain.confidence import (
    Confidence,
    UncertaintyDomain,
    UncertaintyProfile,
    weakest_dependency,
)


def test_ceiling_is_weakest_domain():
    profile = UncertaintyProfile(
        {
            UncertaintyDomain.MODEL: Confidence(1.0),
            UncertaintyDomain.METHOD: Confidence(0.8),
        }
    )
    assert profile.ceiling == Confidence(0.8)


def test_dormant_domain_does_not_cap():
    profile = UncertaintyProfile(
        {
            UncertaintyDomain.MODEL: Confidence(0.9),
            UncertaintyDomain.METHOD: Confidence(0.9),
        }
    )
    # SAGE is dormant and not part of this profile -> does not lower confidence.
    assert profile.get(UncertaintyDomain.SAGE) == Confidence(1.0)
    assert profile.ceiling == Confidence(0.9)


def test_invalid_confidence_rejected():
    with pytest.raises(ValueError):
        Confidence(1.1)
    with pytest.raises(ValueError):
        Confidence(-0.01)


def test_empty_profile_rejected():
    with pytest.raises(ValueError):
        UncertaintyProfile({})


def test_weakest_dependency():
    assert weakest_dependency(Confidence(1.0), Confidence(0.5), Confidence(0.9)) == Confidence(0.5)


def test_weakest_dependency_requires_argument():
    with pytest.raises(ValueError):
        weakest_dependency()


def test_profile_round_trip():
    profile = UncertaintyProfile(
        {UncertaintyDomain.MODEL: Confidence(1.0), UncertaintyDomain.METHOD: Confidence(0.95)}
    )
    restored = UncertaintyProfile.from_dict(profile.to_dict())
    assert restored == profile
    assert restored.ceiling == Confidence(0.95)
