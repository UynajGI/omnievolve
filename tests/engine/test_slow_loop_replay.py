"""Slow Loop replay/promotion 路径测试 — 0% → ~80%."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from omnievolve.engine.slow_loop import SlowLoopController
from omnievolve.meta.governance import MetaAction, RiskLevel


def _make_action(**kwargs):
    """创建 MetaAction 辅助函数."""
    defaults = dict(
        action_type="modify_field",
        target="mutation_rate",
        old_value=0.2,
        new_value=0.3,
        risk_level=RiskLevel.L0,
    )
    defaults.update(kwargs)
    return MetaAction(**defaults)


@pytest.fixture
def slow_loop():
    """创建 SlowLoopController，所有依赖 mock."""
    self_eval = MagicMock()
    self_eval.assess.return_value = MagicMock(
        alert_level=MagicMock(value="ok"),
        roi_score=0.5,
        should_trigger_meta=True,
        coverage_entropy=0.8,
        pollution_ratio=0.1,
    )

    meta_planner = MagicMock()
    action = _make_action()
    meta_planner.propose.return_value = [action]
    meta_planner._tuner = None

    governance = MagicMock()
    governance.can_apply.return_value = (True, "ok")
    governance.classify_action.return_value = MagicMock(value="L0")

    l0_mutator = MagicMock()
    genome = MagicMock()
    genome.to_dict.return_value = {"mutation_rate": 0.3}
    l0_mutator.mutate.return_value = (genome, "ok")

    replay_eval = MagicMock()
    replay_eval.compare.return_value = {"decision": "promote", "gain": 0.1, "reason": "better"}

    policy_archive = MagicMock()
    challenger = MagicMock()
    challenger.id = "challenger-1"
    policy_archive.create_policy.return_value = challenger

    exp_repo = MagicMock()

    prompt_repo = MagicMock()

    return SlowLoopController(
        db=MagicMock(),
        self_evaluator=self_eval,
        meta_planner=meta_planner,
        governance=governance,
        l0_mutator=l0_mutator,
        replay_evaluator=replay_eval,
        policy_archive=policy_archive,
        experiment_repo=exp_repo,
        prompt_repo=prompt_repo,
        artifact_store=MagicMock(),
    )


class TestSlowLoopRun:
    """SlowLoop.run() 主路径."""

    def test_no_evaluator_returns_none(self):
        sl = SlowLoopController(
            db=MagicMock(),
            self_evaluator=None,
            meta_planner=None,
            governance=MagicMock(),
            l0_mutator=MagicMock(),
            replay_evaluator=MagicMock(),
            policy_archive=MagicMock(),
            experiment_repo=MagicMock(),
            prompt_repo=MagicMock(),
            artifact_store=MagicMock(),
        )
        result = sl.run("exp1", 5, 3, MagicMock(), [0.5], "champ-1", "code")
        assert result == (None, None, False)

    def test_telemetry_exception_returns_none(self, slow_loop):
        slow_loop._self_evaluator.assess.side_effect = RuntimeError("DB error")
        result = slow_loop.run("exp1", 5, 3, MagicMock(), [0.5], "champ-1", "code")
        assert result == (None, None, False)

    def test_should_not_trigger_meta(self, slow_loop):
        slow_loop._self_evaluator.assess.return_value = MagicMock(
            should_trigger_meta=False,
            alert_level=MagicMock(value="ok"),
            roi_score=0.5,
            coverage_entropy=0.8,
            pollution_ratio=0.1,
        )
        result = slow_loop.run("exp1", 5, 3, MagicMock(), [0.5], "champ-1", "code")
        assert result == (None, None, True)

    def test_no_meta_planner(self, slow_loop):
        slow_loop._meta_planner = None
        result = slow_loop.run("exp1", 5, 3, MagicMock(), [0.5], "champ-1", "code")
        assert result == (None, None, True)


class TestSlowLoopPromotion:
    """_apply_modify_field → promote/reject 路径."""

    def test_promotion(self, slow_loop):
        """Replay 决策 promote → 返回 new_genome + new_id."""
        search_policy = MagicMock()
        result = slow_loop._apply_meta_action(
            _make_action(),
            current_gen=5,
            experiment_id="exp1",
            search_policy=search_policy,
            champion_policy_id="champ-1",
            recent_scores=[0.4, 0.5, 0.6],
            health_window_gens=3,
            coder_system_prompt="code",
        )
        new_genome, new_id = result
        assert new_id == "challenger-1"
        assert new_genome is not None
        slow_loop._policy_archive.promote_to_champion.assert_called_once_with("challenger-1")
        slow_loop._experiment_repo.set_champion_policy.assert_called_once_with(
            "exp1", "challenger-1"
        )

    def test_rejection(self, slow_loop):
        """Replay 决策 reject → 返回 (None, None)."""
        slow_loop._replay_evaluator.compare.return_value = {
            "decision": "reject",
            "gain": -0.05,
            "reason": "worse",
        }
        result = slow_loop._apply_meta_action(
            _make_action(),
            current_gen=5,
            experiment_id="exp1",
            search_policy=MagicMock(),
            champion_policy_id="champ-1",
            recent_scores=[0.4, 0.5],
            health_window_gens=3,
            coder_system_prompt="code",
        )
        assert result == (None, None)
        slow_loop._policy_archive.reject.assert_called_once()

    def test_governance_rejects(self, slow_loop):
        """治理拒绝 → 返回 (None, None)."""
        slow_loop._governance.can_apply.return_value = (False, "L2 required")
        result = slow_loop._apply_meta_action(
            _make_action(),
            current_gen=5,
            experiment_id="exp1",
            search_policy=MagicMock(),
            champion_policy_id="champ-1",
            recent_scores=[0.5],
            health_window_gens=3,
            coder_system_prompt="code",
        )
        assert result == (None, None)

    def test_mutation_fails(self, slow_loop):
        """L0 mutator 返回 None → 返回 (None, None)."""
        slow_loop._l0_mutator.mutate.return_value = (None, "invalid value")
        result = slow_loop._apply_meta_action(
            _make_action(),
            current_gen=5,
            experiment_id="exp1",
            search_policy=MagicMock(),
            champion_policy_id="champ-1",
            recent_scores=[0.5],
            health_window_gens=3,
            coder_system_prompt="code",
        )
        assert result == (None, None)


class TestSlowLoopEvolvePrompt:
    """_apply_evolve_prompt 路径."""

    def test_evolve_prompt_no_planner(self, slow_loop):
        slow_loop._meta_planner = None
        slow_loop._apply_evolve_prompt(
            _make_action(action_type="evolve_prompt", target="coder"),
            "exp1",
            "system prompt",
        )

    def test_evolve_prompt_empty_prompt(self, slow_loop):
        slow_loop._apply_evolve_prompt(
            _make_action(action_type="evolve_prompt", target="coder"),
            "exp1",
            "",
        )


class TestSafeTunerFeedback:
    """_safe_tuner_feedback 异常保护."""

    def test_exception_does_not_propagate(self, slow_loop):
        """_record_tuner_feedback 崩溃时不传播异常."""
        slow_loop._record_tuner_feedback = MagicMock(side_effect=RuntimeError("DB down"))
        slow_loop._safe_tuner_feedback(
            _make_action(target="x"),
            0.05,
        )
