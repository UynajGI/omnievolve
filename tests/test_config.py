"""config.py 单元测试 — 配置加载、构造器、默认值."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from omnievolve.config import (
    EmbeddingCodeSettings,
    EmbeddingSettings,
    EmbeddingThoughtSettings,
    EvaluationGovernanceSettings,
    EvolutionSettings,
    MetaEvolutionSettings,
    ModelRoutingSettings,
    ModelsSettings,
    NoveltySettings,
    OmniEvolveSettings,
    SandboxDockerSettings,
    SandboxSettings,
    SelectionSettings,
    SelfEvaluatorSettings,
    StorageJobsSettings,
    StorageSettings,
    _build_settings,
    _load_from_toml,
    build_evolution_config,
    build_model_slots,
    build_sandbox_policy,
    load_evaluator,
    load_settings,
)

pytestmark = pytest.mark.unit


# --------------------------------------------------------------------------- #
#  默认值验证
# --------------------------------------------------------------------------- #


class TestEvolutionSettings:
    def test_defaults(self):
        s = EvolutionSettings()
        assert s.max_generations == 50
        assert s.population_size == 8
        assert s.novelty_threshold == 0.92
        assert s.token_budget == 2_000_000

    def test_override(self):
        s = EvolutionSettings(max_generations=10, population_size=2)
        assert s.max_generations == 10
        assert s.population_size == 2


class TestSelectionSettings:
    def test_defaults(self):
        s = SelectionSettings()
        assert s.parent_selector == "progressive_mcgs"
        assert s.tournament_size == 3
        assert s.pareto_enabled is True


class TestModelRoutingSettings:
    def test_defaults(self):
        s = ModelRoutingSettings()
        assert s.algorithm == "sliding_window_ucb"
        assert s.ucb_c == pytest.approx(1.414)


class TestModelsSettings:
    def test_defaults(self):
        s = ModelsSettings()
        assert len(s.heavy) == 1
        assert len(s.light) == 1
        assert isinstance(s.routing, ModelRoutingSettings)

    def test_custom_models(self):
        s = ModelsSettings(heavy=["gpt-4o"], light=["gpt-4o-mini", "claude-haiku"])
        assert s.heavy == ["gpt-4o"]
        assert len(s.light) == 2


class TestEmbeddingCodeSettings:
    def test_defaults(self):
        s = EmbeddingCodeSettings()
        assert s.provider == "voyage"
        assert s.dimension == 1024

    def test_local_config(self):
        s = EmbeddingCodeSettings(provider="local", model="all-MiniLM-L6-v2", dimension=384)
        assert s.provider == "local"
        assert s.dimension == 384


class TestEmbeddingThoughtSettings:
    def test_defaults(self):
        s = EmbeddingThoughtSettings()
        assert s.provider == "local"
        assert s.model == "bge-m3"


class TestNoveltySettings:
    def test_defaults(self):
        s = NoveltySettings()
        assert s.embedding_gate is True
        assert s.behavior_gate is False
        assert s.borderline_low == 0.88


class TestSandboxDockerSettings:
    def test_defaults(self):
        s = SandboxDockerSettings()
        assert "omnievolve" in s.image
        assert s.tmpfs_mb == 256


class TestSandboxSettings:
    def test_defaults(self):
        s = SandboxSettings()
        assert s.backend == "docker"
        assert s.network_mode == "none"
        assert s.read_only_root is True
        assert s.run_as_non_root is True


class TestStorageSettings:
    def test_defaults(self):
        s = StorageSettings()
        assert ".omnievolve" in s.db_path
        assert isinstance(s.jobs, StorageJobsSettings)


class TestStorageJobsSettings:
    def test_defaults(self):
        s = StorageJobsSettings()
        assert s.lease_sec == 120
        assert s.max_attempts == 3


class TestSelfEvaluatorSettings:
    def test_defaults(self):
        s = SelfEvaluatorSettings()
        assert s.roi_warn_threshold == 0.001
        assert s.stagnation_trigger == 3


class TestMetaEvolutionSettings:
    def test_defaults(self):
        s = MetaEvolutionSettings()
        assert s.enabled is True
        assert s.auto_apply_l0 is True
        assert s.allow_l2_actions is False


class TestEvaluationGovernanceSettings:
    def test_defaults(self):
        s = EvaluationGovernanceSettings()
        assert s.immutable_task_semantics is True
        assert s.immutable_score_formula is True


# --------------------------------------------------------------------------- #
#  OmniEvolveSettings — 顶层配置
# --------------------------------------------------------------------------- #


class TestOmniEvolveSettings:
    def test_all_sections_have_defaults(self):
        s = OmniEvolveSettings()
        assert isinstance(s.evolution, EvolutionSettings)
        assert isinstance(s.selection, SelectionSettings)
        assert isinstance(s.models, ModelsSettings)
        assert isinstance(s.embedding, EmbeddingSettings)
        assert isinstance(s.novelty, NoveltySettings)
        assert isinstance(s.sandbox, SandboxSettings)
        assert isinstance(s.storage, StorageSettings)
        assert isinstance(s.self_evaluator, SelfEvaluatorSettings)
        assert isinstance(s.meta_evolution, MetaEvolutionSettings)
        assert isinstance(s.evaluation_governance, EvaluationGovernanceSettings)

    def test_env_prefix(self):
        assert OmniEvolveSettings.model_config["env_prefix"] == "OMNIEVOLVE_"


# --------------------------------------------------------------------------- #
#  load_settings
# --------------------------------------------------------------------------- #


class TestLoadSettings:
    def test_no_config_returns_defaults(self):
        settings = load_settings(None)
        assert isinstance(settings, OmniEvolveSettings)

    def test_missing_file_returns_defaults(self):
        settings = load_settings("/nonexistent/path.toml")
        assert isinstance(settings, OmniEvolveSettings)

    def test_load_from_toml_file(self):
        toml_content = """
[evolution]
max_generations = 5
population_size = 2

[models]
heavy = ["gpt-4o"]
light = ["gpt-4o-mini"]

[sandbox]
backend = "trusted_subprocess"
        """
        with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
            f.write(toml_content)
            tmp_path = f.name

        try:
            settings = _load_from_toml(tmp_path)
            assert settings.evolution.max_generations == 5
            assert settings.evolution.population_size == 2
            assert settings.models.heavy == ["gpt-4o"]
            assert settings.sandbox.backend == "trusted_subprocess"
        finally:
            Path(tmp_path).unlink()


# --------------------------------------------------------------------------- #
#  _build_settings
# --------------------------------------------------------------------------- #


class TestBuildSettings:
    def test_empty_dict_uses_defaults(self):
        s = _build_settings({})
        assert s.evolution.max_generations == 50

    def test_partial_override(self):
        s = _build_settings({"evolution": {"max_generations": 3}})
        assert s.evolution.max_generations == 3
        assert s.evolution.population_size == 8  # default

    def test_nested_embedding(self):
        s = _build_settings(
            {
                "embedding": {
                    "code": {"provider": "local", "model": "test-model"},
                    "thought": {"provider": "openai"},
                }
            }
        )
        assert s.embedding.code.provider == "local"
        assert s.embedding.thought.provider == "openai"

    def test_nested_sandbox_docker(self):
        s = _build_settings(
            {"sandbox": {"backend": "trusted_subprocess", "docker": {"image": "custom:latest"}}}
        )
        assert s.sandbox.backend == "trusted_subprocess"
        assert s.sandbox.docker.image == "custom:latest"


# --------------------------------------------------------------------------- #
#  Component builders
# --------------------------------------------------------------------------- #


class TestBuildEvolutionConfig:
    def test_returns_config(self):
        s = OmniEvolveSettings()
        cfg = build_evolution_config(s)
        assert cfg.max_generations == 50
        assert cfg.population_size == 8


class TestBuildSandboxPolicy:
    def test_returns_policy(self):
        s = OmniEvolveSettings()
        policy = build_sandbox_policy(s)
        assert policy.network_mode == "none"
        assert policy.read_only_root is True


class TestBuildModelSlots:
    def test_returns_slots(self):
        s = OmniEvolveSettings()
        slots = build_model_slots(s)
        assert len(slots) >= 2
        assert slots[0].tier == "heavy"
        assert slots[1].tier == "light"


# --------------------------------------------------------------------------- #
#  load_evaluator
# --------------------------------------------------------------------------- #


class TestLoadEvaluator:
    def test_load_by_module_colon_class(self):
        cls = load_evaluator("omnievolve.eval.demo_evaluator:PythonUnitTestEvaluator")
        assert cls is not None

    def test_load_by_dotted_path(self):
        cls = load_evaluator("omnievolve.eval.demo_evaluator.PythonUnitTestEvaluator")
        assert cls is not None

    def test_invalid_spec_raises(self):
        with pytest.raises(ValueError, match="Invalid evaluator spec"):
            load_evaluator("no_dots_or_colons")
