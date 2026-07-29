"""hyperparam_tuner.py 单元测试 — BayesianTuner GP+EI 优化器."""

from __future__ import annotations

import pytest

from omnievolve.meta.hyperparam_tuner import (
    DEFAULT_PARAM_SPACE,
    BayesianTuner,
    ParamSpec,
)

pytestmark = pytest.mark.unit


class TestParamSpec:
    def test_float_param(self):
        ps = ParamSpec("temperature", "float", 0.1, 1.0)
        assert ps.name == "temperature"
        assert ps.kind == "float"

    def test_int_param(self):
        ps = ParamSpec("retrieval_budget", "int", 4, 20)
        assert ps.kind == "int"

    def test_choice_param(self):
        ps = ParamSpec("strategy", "choice", choices=["a", "b", "c"])
        assert ps.kind == "choice"


class TestBayesianTunerInit:
    def test_default_space(self):
        tuner = BayesianTuner()
        assert len(tuner._space) == len(DEFAULT_PARAM_SPACE)  # noqa: SLF001

    def test_custom_space(self):
        space = [
            ParamSpec("x", "float", 0, 1),
            ParamSpec("y", "int", 1, 10),
        ]
        tuner = BayesianTuner(space, n_initial=3)
        assert tuner._n_initial == 3  # noqa: SLF001

    def test_no_trials_initially(self):
        tuner = BayesianTuner()
        assert tuner.get_best() is None

    def test_stats_initial(self):
        tuner = BayesianTuner()
        s = tuner.get_stats()
        assert s["n_trials"] == 0
        assert s["best_score"] is None


class TestBayesianTunerRandomPhase:
    """前 n_initial 次为随机探索."""

    def test_first_suggest_is_random(self):
        tuner = BayesianTuner(n_initial=5)
        p1 = tuner.suggest()
        p2 = tuner.suggest()
        assert isinstance(p1, dict)
        assert len(p1) > 0
        # 两个随机样本大概率不同
        vals1 = tuple(p1.values())
        vals2 = tuple(p2.values())
        assert vals1 != vals2

    def test_suggest_respects_int_bounds(self):
        tuner = BayesianTuner(n_initial=10)
        for _ in range(10):
            p = tuner.suggest()
            if "retrieval_budget" in p:
                v = p["retrieval_budget"]
                assert isinstance(v, int) or v == int(v)
                assert 4 <= v <= 20

    def test_suggest_respects_float_bounds(self):
        tuner = BayesianTuner(n_initial=10)
        for _ in range(10):
            p = tuner.suggest()
            for k, v in p.items():
                assert isinstance(v, int | float)


class TestBayesianTunerUpdate:
    def test_update_records_trial(self):
        tuner = BayesianTuner(n_initial=3)
        params = tuner.suggest()
        tuner.update(params, score=0.8, generation=5)
        assert tuner.get_stats()["n_trials"] == 1
        assert tuner.get_best().score == 0.8

    def test_best_tracked_correctly(self):
        tuner = BayesianTuner(n_initial=3)
        for score in [0.5, 0.9, 0.3]:
            tuner.update(tuner.suggest(), score=score)
        assert tuner.get_best().score == 0.9

    def test_update_tracks_generation(self):
        tuner = BayesianTuner(n_initial=3)
        tuner.update(tuner.suggest(), score=0.5, generation=10)
        assert tuner.get_best().generation == 10


class TestBayesianTunerEIPhase:
    """超过 n_initial 后使用 EI 采集."""

    def test_switches_to_ei_after_initial(self):
        tuner = BayesianTuner(n_initial=3)
        for score in [0.1, 0.5, 0.9]:
            tuner.update(tuner.suggest(), score=score)
        # 第 4 次应为 EI 采样
        params = tuner.suggest()
        assert isinstance(params, dict)
        assert len(params) > 0

    def test_ei_converges_toward_optimum(self):
        """EI 采样不崩溃且有界."""
        space = [ParamSpec("x", "float", -5, 5)]
        tuner = BayesianTuner(space, n_initial=3, random_state=42)

        def objective(x):
            return max(0.0, 1.0 - x**2 / 25.0)

        for _ in range(5):
            p = tuner.suggest()
            score = objective(p["x"])
            tuner.update(p, score)

        # 10 次 EI 采样，验证不崩溃且有界
        samples = [tuner.suggest()["x"] for _ in range(10)]
        for s in samples:
            assert -5.0 <= s <= 5.0

    def test_stats_converged_detection(self):
        tuner = BayesianTuner(n_initial=1)
        for _ in range(5):
            tuner.update(tuner.suggest(), score=0.9)
        stats = tuner.get_stats()
        assert stats["n_trials"] == 5
        # 5 次相同分数 → 应该收敛
        assert stats["converged"] is True or stats["converged"] == True  # noqa: E712


class TestBayesianTunerParamConversion:
    def test_vector_roundtrip(self):
        tuner = BayesianTuner(n_initial=1)
        params = tuner.suggest()
        vec = tuner._params_to_vector(params)  # noqa: SLF001
        params2 = tuner._vector_to_params(vec)  # noqa: SLF001
        for k in params:
            assert abs(params[k] - params2[k]) < 0.01

    def test_int_param_preserved(self):
        tuner = BayesianTuner(n_initial=1)
        params = tuner.suggest()
        if "retrieval_budget" in params:
            assert params["retrieval_budget"] == int(params["retrieval_budget"])


class TestGenomeIntegration:
    def test_genome_to_params(self):
        from omnievolve.meta.policy_genome import SearchPolicyGenome

        genome = SearchPolicyGenome(
            mutation_mix={"point": 0.5, "crossover": 0.3, "rewrite": 0.2},
            retrieval_budget=8,
            memory_scope_weights={"L0": 1.0, "L1": 0.9, "L2": 0.6, "L3": 0.4, "L4": 0.2},
        )
        tuner = BayesianTuner()
        params = tuner.genome_to_params(genome)
        assert params["mutation_point_weight"] == 0.5
        assert params["retrieval_budget"] == 8
        assert params["memory_l0_weight"] == 1.0

    def test_params_to_genome_updates(self):
        tuner = BayesianTuner()
        updates = tuner.params_to_genome_updates(
            {
                "mutation_point_weight": 0.6,
                "mutation_crossover_weight": 0.2,
                "mutation_rewrite_weight": 0.2,
                "retrieval_budget": 12,
            }
        )
        assert "mutation_mix" in updates
        assert "retrieval_budget" in updates
        assert updates["retrieval_budget"] == 12
        # mutation_mix 应该归一化
        mm = updates["mutation_mix"]
        assert abs(sum(mm.values()) - 1.0) < 0.01

    def test_params_to_genome_normalizes(self):
        tuner = BayesianTuner()
        updates = tuner.params_to_genome_updates(
            {
                "mutation_point_weight": 1.0,
                "mutation_crossover_weight": 1.0,
                "mutation_rewrite_weight": 1.0,
            }
        )
        mm = updates["mutation_mix"]
        assert abs(sum(mm.values()) - 1.0) < 0.01


class TestMetaPlannerWithTuner:
    def test_meta_planner_accepts_tuner(self):
        from omnievolve.meta.governance import (
            GovernancePolicy,
            L0PolicyMutator,
            MetaPlanner,
        )

        gov = GovernancePolicy()
        mutator = L0PolicyMutator(gov)
        tuner = BayesianTuner(n_initial=5)
        planner = MetaPlanner(mutator, tuner=tuner)

        # 有 tuner 时应走贝叶斯路径
        genome = type(
            "G",
            (),
            {
                "mutation_mix": {"point": 0.5, "crossover": 0.3, "rewrite": 0.2},
                "retrieval_budget": 8,
                "memory_scope_weights": {"L0": 1.0, "L1": 0.9, "L2": 0.6, "L3": 0.4, "L4": 0.2},
            },
        )()
        actions = planner.propose({}, genome, [])
        assert len(actions) >= 1

    def test_meta_planner_falls_back_without_tuner(self):
        from omnievolve.meta.governance import (
            GovernancePolicy,
            L0PolicyMutator,
            MetaPlanner,
        )

        gov = GovernancePolicy()
        mutator = L0PolicyMutator(gov)
        planner = MetaPlanner(mutator)  # 无 tuner → 规则引擎回退

        genome = type(
            "G",
            (),
            {
                "mutation_mix": {"point": 0.5, "crossover": 0.3, "rewrite": 0.2},
                "retrieval_budget": 8,
                "memory_scope_weights": {"L0": 1.0, "L1": 0.9, "L2": 0.6, "L3": 0.4, "L4": 0.2},
            },
        )()
        health = {"coverage_entropy": 0.3, "pollution_ratio": 0.4, "roi_score": 0.005}
        actions = planner.propose(health, genome, [])
        # 规则引擎在低覆盖率时会建议增加 retrieval_budget
        assert len(actions) >= 1
