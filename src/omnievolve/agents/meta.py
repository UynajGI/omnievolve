"""Meta Agent - 策略优化 Agent.

S8-10: 实现 MetaPlanner 只读诊断
"""

from __future__ import annotations

import logging
from typing import Any

from omnievolve.meta.governance import MetaAction, MetaPlanner
from omnievolve.meta.policy_genome import SearchPolicyGenome

logger = logging.getLogger(__name__)


class MetaAgent:
    """Meta Agent - 负责策略进化（Slow Loop）."""

    def __init__(self, planner: MetaPlanner) -> None:
        self._planner = planner

    def optimize(
        self,
        health: dict[str, Any],
        champion_policy: dict[str, Any] | SearchPolicyGenome,
        history: list[dict],
    ) -> list[MetaAction]:
        """提议优化动作."""
        if isinstance(champion_policy, dict):
            genome = SearchPolicyGenome.from_dict(champion_policy)
        else:
            genome = champion_policy

        return self._planner.propose(health, genome, history)
