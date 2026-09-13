"""Tests for model bench registry — Phase 3 model integration."""

import pytest

from sage_research.domain.model_registry import (
    MODEL_REGISTRY,
    BenchModel,
    get_model,
    iter_models,
)


class TestModelRegistry:
    """Test suite for Phase 3 model bench registry."""

    def test_registry_contains_phase3_models(self):
        """Registry includes all Phase 3 target models."""
        keys = {model.key for model in MODEL_REGISTRY}

        # Phase 3 requirements from capability-plan.md
        assert "gpt2-small" in keys
        assert "openelm-270m" in keys
        assert "olmo-3" in keys
        assert "smollm2-135m" in keys
        assert "qwen2.5-0.5b" in keys
        assert "qwen3-0.6b" in keys

        # Plus the original baseline
        assert "pythia-70m" in keys

    def test_pythia_baseline_preserved(self):
        """Pythia-70M remains as Research Specimen 001."""
        pythia = get_model("pythia-70m")

        assert pythia.name == "Pythia-70M"
        assert pythia.family == "pythia"
        assert "EleutherAI/pythia-70m" in pythia.hf_candidates
        assert "baseline" in pythia.tags
        assert "Research Specimen 001" in pythia.notes

    def test_gpt2_small_configuration(self):
        """GPT-2 Small configured as canonical baseline."""
        gpt2 = get_model("gpt2-small")

        assert gpt2.name == "GPT-2 Small"
        assert gpt2.family == "gpt2"
        assert "openai-community/gpt2" in gpt2.hf_candidates
        assert "baseline" in gpt2.tags
        assert gpt2.parameter_hint == "~124M"

    def test_openelm_configuration(self):
        """OpenELM configured for efficient architecture testing."""
        openelm = get_model("openelm-270m")

        assert openelm.name == "OpenELM-270M"
        assert openelm.family == "openelm"
        assert "apple/OpenELM-270M" in openelm.hf_candidates
        assert "efficient-architecture" in openelm.tags
        assert "layer-wise scaling" in openelm.notes.lower()

    def test_olmo3_fallback_strategy(self):
        """OLMo 3 has fallback to OLMo 2 for availability."""
        olmo = get_model("olmo-3")

        assert olmo.name == "OLMo 3"
        assert olmo.family == "olmo"
        # Prefer OLMo 3, fall back to verified OLMo 2
        assert len(olmo.hf_candidates) >= 2
        assert any("OLMo-3" in candidate for candidate in olmo.hf_candidates)
        assert any("OLMo-2" in candidate for candidate in olmo.hf_candidates)
        assert "open-data" in olmo.tags

    def test_smollm2_configuration(self):
        """SmolLM2 configured as strong cheap challenger."""
        smollm2 = get_model("smollm2-135m")

        assert smollm2.name == "SmolLM2-135M"
        assert smollm2.family == "smollm2"
        assert "HuggingFaceTB/SmolLM2-135M" in smollm2.hf_candidates
        assert "challenger" in smollm2.tags
        assert smollm2.parameter_hint == "~135M"

    def test_qwen25_configuration(self):
        """Qwen2.5 configured as brain-capability reference."""
        qwen25 = get_model("qwen2.5-0.5b")

        assert qwen25.name == "Qwen2.5-0.5B"
        assert qwen25.family == "qwen2.5"
        assert "Qwen/Qwen2.5-0.5B" in qwen25.hf_candidates
        assert "brain" in qwen25.tags
        assert "challenger" in qwen25.tags

    def test_qwen3_configuration(self):
        """Qwen3 configured as newest brain reference."""
        qwen3 = get_model("qwen3-0.6b")

        assert qwen3.name == "Qwen3-0.6B"
        assert qwen3.family == "qwen3"
        assert "Qwen/Qwen3-0.6B" in qwen3.hf_candidates
        assert "brain" in qwen3.tags
        assert "Newest" in qwen3.notes or "newest" in qwen3.notes

    def test_all_models_have_tinystories_suite(self):
        """All models default to TinyStories evaluation suite."""
        for model in MODEL_REGISTRY:
            assert model.eval_suite == "tinystories"

    def test_primary_source_format(self):
        """Primary source has correct format for loaders."""
        for model in MODEL_REGISTRY:
            source = model.primary_source
            assert source.startswith("huggingface:")
            assert ":" in source
            # Should contain the first HF candidate
            assert model.hf_candidates[0] in source

    def test_model_serialization(self):
        """Models serialize to dict correctly."""
        pythia = get_model("pythia-70m")
        data = pythia.to_dict()

        assert data["key"] == "pythia-70m"
        assert data["name"] == "Pythia-70M"
        assert data["family"] == "pythia"
        assert isinstance(data["hf_candidates"], list)
        assert isinstance(data["tags"], list)
        assert data["eval_suite"] == "tinystories"

    def test_get_model_raises_on_unknown(self):
        """get_model raises KeyError with helpful message for unknown key."""
        with pytest.raises(KeyError) as exc_info:
            get_model("nonexistent-model")

        assert "nonexistent-model" in str(exc_info.value)
        assert "known keys:" in str(exc_info.value).lower()

    def test_iter_models_returns_all(self):
        """iter_models returns complete registry in order."""
        models = iter_models()

        assert len(models) == len(MODEL_REGISTRY)
        assert models == MODEL_REGISTRY

    def test_model_keys_unique(self):
        """All model keys are unique."""
        keys = [model.key for model in MODEL_REGISTRY]
        assert len(keys) == len(set(keys))

    def test_parameter_hints_present(self):
        """All models have parameter count hints."""
        for model in MODEL_REGISTRY:
            assert model.parameter_hint
            assert "~" in model.parameter_hint or "M" in model.parameter_hint or "B" in model.parameter_hint

    def test_hf_candidates_nonempty(self):
        """Every model has at least one HF candidate."""
        for model in MODEL_REGISTRY:
            assert len(model.hf_candidates) > 0

    def test_baseline_vs_challenger_tags(self):
        """Models are tagged appropriately by role."""
        baselines = [m for m in MODEL_REGISTRY if "baseline" in m.tags]
        challengers = [m for m in MODEL_REGISTRY if "challenger" in m.tags]

        # 2 baselines (Pythia + GPT-2)
        assert len(baselines) == 2
        # 3 challengers (SmolLM2, Qwen2.5, Qwen3)
        assert len(challengers) == 3

    def test_phase3_diversity(self):
        """Phase 3 models span different families."""
        families = {model.family for model in MODEL_REGISTRY}

        # Should have good family diversity
        assert "pythia" in families
        assert "gpt2" in families
        assert "openelm" in families
        assert "olmo" in families
        assert "smollm2" in families
        assert "qwen2.5" in families
        assert "qwen3" in families
