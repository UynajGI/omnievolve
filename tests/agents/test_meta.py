"""MetaAgent 测试 — 验证 planner 委托传递."""

from __future__ import annotations

from unittest.mock import MagicMock

from omnievolve.agents.meta import MetaAgent
from omnievolve.meta.governance import MetaAction, MetaPlanner
from omnievolve.meta.policy_genome import SearchPolicyGenome


class TestMetaAgent:
    def test_delegates_to_planner(self):
        """MetaAgent.optimize() 应委托给 MetaPlanner.propose()."""
        from omnievolve.meta.governance import RiskLevel

        mock_planner = MagicMock(spec=MetaPlanner)
        mock_action = MetaAction(
            action_type="evolve_prompt",
            target="coder",
            old_value="old_prompt",
            new_value="new_prompt",
            risk_level=RiskLevel.L1,
            rationale="test action",
        )
        mock_planner.propose.return_value = [mock_action]

        agent = MetaAgent(mock_planner)
        health = {"roi_score": 0.001, "coverage_entropy": 0.2}
        champion = SearchPolicyGenome()
        history: list[dict] = []

        result = agent.optimize(health, champion, history)

        assert len(result) == 1
        assert result[0].action_type == "evolve_prompt"
        mock_planner.propose.assert_called_once()

    def test_converts_dict_champion(self):
        """champion_policy 是 dict 时自动转换为 SearchPolicyGenome."""
        mock_planner = MagicMock(spec=MetaPlanner)
        mock_planner.propose.return_value = []

        agent = MetaAgent(mock_planner)
        health = {"roi": 0.5}
        champion = {"model_routing_policy": "sliding_ucb"}
        history: list[dict] = []

        result = agent.optimize(health, champion, history)

        assert result == []
        # Verify it was called with a SearchPolicyGenome
        call_args = mock_planner.propose.call_args[0]
        assert isinstance(call_args[1], SearchPolicyGenome)
