"""Task/stage-conditioned operator bandit for code evolution."""

from __future__ import annotations

import math
import random
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Literal

OperatorName = Literal["point", "diff", "rewrite", "crossover", "repair"]
DEFAULT_OPERATORS: tuple[OperatorName, ...] = (
    "point",
    "diff",
    "rewrite",
    "crossover",
    "repair",
)


@dataclass(frozen=True)
class OperatorDecision:
    operator: OperatorName
    task: str
    stage: str
    algorithm: str


class OperatorPortfolio:
    """UCB/Thompson scheduler whose rewards are child-vs-parent gains."""

    def __init__(
        self,
        *,
        algorithm: Literal["ucb", "thompson"] = "ucb",
        operators: Iterable[OperatorName] = DEFAULT_OPERATORS,
        exploration: float = 1.414,
    ) -> None:
        if algorithm not in {"ucb", "thompson"}:
            raise ValueError(f"unsupported operator portfolio algorithm: {algorithm!r}")
        operator_tuple = tuple(dict.fromkeys(operators))
        if not operator_tuple:
            raise ValueError("operator portfolio requires at least one operator")
        unknown = set(operator_tuple) - set(DEFAULT_OPERATORS)
        if unknown:
            raise ValueError(f"unsupported operators: {sorted(unknown)!r}")
        self._algorithm = algorithm
        self._operators = operator_tuple
        self._exploration = float(exploration)
        self._state: dict[str, dict[str, dict[str, float]]] = {}

    @staticmethod
    def _context_key(task: str, stage: str) -> str:
        return f"{task}\x1f{stage}"

    def _ensure_context(self, task: str, stage: str) -> dict[str, dict[str, float]]:
        return self._state.setdefault(
            self._context_key(task, stage),
            {
                operator: {"count": 0.0, "reward_sum": 0.0, "alpha": 1.0, "beta": 1.0}
                for operator in self._operators
            },
        )

    def select(
        self,
        *,
        task: str,
        stage: str,
        eligible: Iterable[OperatorName],
    ) -> OperatorDecision:
        eligible_set = set(eligible)
        candidates = [operator for operator in self._operators if operator in eligible_set]
        if not candidates:
            raise ValueError("operator portfolio has no eligible operator")
        state = self._ensure_context(task, stage)

        if self._algorithm == "thompson":
            chosen = max(
                candidates,
                key=lambda operator: (
                    random.betavariate(state[operator]["alpha"], state[operator]["beta"]),
                    -self._operators.index(operator),
                ),
            )
        else:
            untried = [operator for operator in candidates if state[operator]["count"] == 0]
            if untried:
                chosen = untried[0]
            else:
                total = max(1.0, sum(state[operator]["count"] for operator in candidates))
                chosen = max(
                    candidates,
                    key=lambda operator: (
                        state[operator]["reward_sum"] / state[operator]["count"]
                        + self._exploration
                        * math.sqrt(math.log(total + 1.0) / state[operator]["count"]),
                        -self._operators.index(operator),
                    ),
                )
        return OperatorDecision(chosen, task, stage, self._algorithm)

    def update(
        self,
        decision: OperatorDecision,
        *,
        relative_gain: float,
        passed: bool,
    ) -> None:
        if decision.algorithm != self._algorithm:
            raise ValueError("operator decision algorithm does not match portfolio")
        state = self._ensure_context(decision.task, decision.stage)[decision.operator]
        normalized = 0.5 + 0.5 * max(-1.0, min(1.0, float(relative_gain)))
        if not passed:
            normalized = 0.0
        state["count"] += 1.0
        state["reward_sum"] += normalized
        state["alpha"] += normalized
        state["beta"] += 1.0 - normalized

    def get_stats(self) -> dict[str, Any]:
        return {
            "algorithm": self._algorithm,
            "operators": list(self._operators),
            "contexts": self._state,
        }

    def snapshot_state(self) -> dict[str, Any]:
        return {
            "algorithm": self._algorithm,
            "operators": list(self._operators),
            "exploration": self._exploration,
            "state": self._state,
        }

    def restore_state(self, state: dict[str, Any] | None) -> None:
        if not state:
            return
        if state.get("algorithm") != self._algorithm:
            raise ValueError("operator portfolio checkpoint algorithm does not match runtime")
        if tuple(state.get("operators", [])) != self._operators:
            raise ValueError("operator portfolio checkpoint operators do not match runtime")
        if float(state.get("exploration", self._exploration)) != self._exploration:
            raise ValueError("operator portfolio checkpoint exploration does not match runtime")
        restored: dict[str, dict[str, dict[str, float]]] = {}
        for context, operators in state.get("state", {}).items():
            restored[str(context)] = {}
            for operator in self._operators:
                payload = operators.get(operator)
                if payload is None:
                    raise ValueError("operator portfolio checkpoint is incomplete")
                restored[str(context)][operator] = {
                    key: float(payload[key])
                    for key in ("count", "reward_sum", "alpha", "beta")
                }
        self._state = restored
