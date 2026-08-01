"""Independent, equal-budget policy replay contracts.

The Slow Loop must never infer challenger quality from champion history.  A
replay executor runs both policy genomes on the same frozen cases and returns
the measurements needed by :class:`ReplayEvaluator`.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Protocol

from omnievolve.meta.policy_genome import SearchPolicyGenome
from omnievolve.meta.policy_runtime import validate_policy_change


@dataclass(frozen=True)
class PolicyReplayRequest:
    """A paired champion/challenger replay over one immutable snapshot."""

    experiment_id: str
    champion_policy_id: str
    challenger_policy_id: str
    champion: SearchPolicyGenome
    challenger: SearchPolicyGenome
    snapshot_id: str
    seeds: tuple[int, ...]
    token_budget_per_arm: int
    wall_budget_sec_per_arm: float | None = None
    require_known_cost: bool = False
    task_name: str = ""
    frontier_refs: tuple[str, ...] = ()
    generations_per_seed: int = 1

    def __post_init__(self) -> None:
        if not self.snapshot_id:
            raise ValueError("policy replay requires a frozen snapshot_id")
        if len(self.seeds) < 3:
            raise ValueError("policy replay requires at least three paired seeds")
        if len(set(self.seeds)) != len(self.seeds):
            raise ValueError("policy replay seeds must be unique")
        if self.token_budget_per_arm <= 0:
            raise ValueError("token_budget_per_arm must be positive")
        if self.token_budget_per_arm < len(self.seeds):
            raise ValueError("token_budget_per_arm must allocate at least one token per seed")
        if self.wall_budget_sec_per_arm is not None and self.wall_budget_sec_per_arm <= 0:
            raise ValueError("wall_budget_sec_per_arm must be positive when set")
        if self.generations_per_seed < 1:
            raise ValueError("generations_per_seed must be positive")

    @property
    def token_budget_per_seed(self) -> int:
        """Equal integer ceiling assigned to every paired seed."""
        return self.token_budget_per_arm // len(self.seeds)

    @property
    def wall_budget_sec_per_seed(self) -> float | None:
        if self.wall_budget_sec_per_arm is None:
            return None
        return self.wall_budget_sec_per_arm / len(self.seeds)


@dataclass(frozen=True)
class PolicyReplayEvidence:
    """Auditable measurements from independent paired executions."""

    snapshot_id: str
    seeds: tuple[int, ...]
    champion_scores: tuple[float, ...]
    challenger_scores: tuple[float, ...]
    champion_tokens: int
    challenger_tokens: int
    champion_best_scores: tuple[float, ...] = ()
    challenger_best_scores: tuple[float, ...] = ()
    champion_success_rates: tuple[float, ...] = ()
    challenger_success_rates: tuple[float, ...] = ()
    champion_cost_usd: float | None = None
    challenger_cost_usd: float | None = None
    champion_wall_sec: float = 0.0
    challenger_wall_sec: float = 0.0
    champion_token_budget: int | None = None
    challenger_token_budget: int | None = None
    integrity_passed: bool = True
    anti_cheat_passed: bool = True
    independent_executions: bool = True

    def validate_for(self, request: PolicyReplayRequest) -> None:
        """Fail closed unless evidence proves a matched, equal-budget replay."""
        if not self.independent_executions:
            raise ValueError("policy replay evidence is not from independent executions")
        if self.snapshot_id != request.snapshot_id:
            raise ValueError("policy replay snapshot does not match request")
        if self.seeds != request.seeds:
            raise ValueError("policy replay seeds do not match request")
        if len(self.champion_scores) != len(request.seeds):
            raise ValueError("champion replay did not produce one score per seed")
        if len(self.challenger_scores) != len(request.seeds):
            raise ValueError("challenger replay did not produce one score per seed")
        if not self.integrity_passed or not self.anti_cheat_passed:
            raise ValueError("policy replay failed integrity or anti-cheat guardrails")
        if not all(
            math.isfinite(value) for value in (*self.champion_scores, *self.challenger_scores)
        ):
            raise ValueError("policy replay scores must be finite")
        if self.champion_best_scores and len(self.champion_best_scores) != len(request.seeds):
            raise ValueError("champion replay best-score count does not match paired seeds")
        if self.challenger_best_scores and len(self.challenger_best_scores) != len(request.seeds):
            raise ValueError("challenger replay best-score count does not match paired seeds")
        if self.champion_success_rates and len(self.champion_success_rates) != len(request.seeds):
            raise ValueError("champion replay success-rate count does not match paired seeds")
        if self.challenger_success_rates and len(self.challenger_success_rates) != len(
            request.seeds
        ):
            raise ValueError("challenger replay success-rate count does not match paired seeds")
        champion_ceiling = self.champion_token_budget or request.token_budget_per_arm
        challenger_ceiling = self.challenger_token_budget or request.token_budget_per_arm
        if (
            champion_ceiling != challenger_ceiling
            or champion_ceiling != request.token_budget_per_arm
        ):
            raise ValueError("policy replay arms did not use the same configured token budget")
        if self.champion_tokens > request.token_budget_per_arm:
            raise ValueError("champion exceeded replay token budget")
        if self.challenger_tokens > request.token_budget_per_arm:
            raise ValueError("challenger exceeded replay token budget")
        if request.wall_budget_sec_per_arm is not None:
            if self.champion_wall_sec > request.wall_budget_sec_per_arm:
                raise ValueError("champion exceeded replay wall budget")
            if self.challenger_wall_sec > request.wall_budget_sec_per_arm:
                raise ValueError("challenger exceeded replay wall budget")
        if request.require_known_cost and (
            self.champion_cost_usd is None or self.challenger_cost_usd is None
        ):
            raise ValueError("policy replay requires known costs for both arms")


@dataclass(frozen=True)
class PolicyArmResult:
    """One independently executed policy/seed arm."""

    frontier_auc: float
    best_score: float
    success_rate: float
    tokens: int
    wall_sec: float
    cost_usd: float | None = None
    integrity_passed: bool = True
    anti_cheat_passed: bool = True

    def validate(self, request: PolicyReplayRequest) -> None:
        if not all(
            math.isfinite(value)
            for value in (self.frontier_auc, self.best_score, self.success_rate, self.wall_sec)
        ):
            raise ValueError("policy arm returned non-finite measurements")
        if not 0.0 <= self.success_rate <= 1.0:
            raise ValueError("policy arm success_rate must be in [0, 1]")
        if self.tokens < 0 or self.tokens > request.token_budget_per_seed:
            raise ValueError("policy arm exceeded token budget")
        if (
            request.wall_budget_sec_per_seed is not None
            and self.wall_sec > request.wall_budget_sec_per_seed
        ):
            raise ValueError("policy arm exceeded wall budget")
        if not self.integrity_passed or not self.anti_cheat_passed:
            raise ValueError("policy arm failed integrity checks")


class PolicyArmRunner(Protocol):
    """Runtime adapter that executes one policy against a frozen snapshot."""

    def run_arm(
        self,
        *,
        request: PolicyReplayRequest,
        policy: SearchPolicyGenome,
        policy_id: str,
        seed: int,
        arm: str,
    ) -> PolicyArmResult:
        """Execute one independent arm with the request's hard ceilings."""
        ...


class PolicyCanaryRunner:
    """Production paired-arm orchestration over a frozen frontier snapshot."""

    def __init__(self, arm_runner: PolicyArmRunner) -> None:
        self._arm_runner = arm_runner

    def run_paired(self, request: PolicyReplayRequest) -> PolicyReplayEvidence:
        live, inactive_changes = validate_policy_change(request.champion, request.challenger)
        if not live:
            raise ValueError(
                "challenger changes inactive policy fields: " + ", ".join(inactive_changes)
            )

        champion: list[PolicyArmResult] = []
        challenger: list[PolicyArmResult] = []
        for index, seed in enumerate(request.seeds):
            # Alternate order to reduce monotonic provider/runtime drift.
            arms = (
                (
                    ("champion", request.champion, request.champion_policy_id, champion),
                    ("challenger", request.challenger, request.challenger_policy_id, challenger),
                )
                if index % 2 == 0
                else (
                    ("challenger", request.challenger, request.challenger_policy_id, challenger),
                    ("champion", request.champion, request.champion_policy_id, champion),
                )
            )
            for arm, policy, policy_id, destination in arms:
                started = time.monotonic()
                result = self._arm_runner.run_arm(
                    request=request,
                    policy=policy,
                    policy_id=policy_id,
                    seed=seed,
                    arm=arm,
                )
                result.validate(request)
                if result.wall_sec <= 0:
                    result = PolicyArmResult(
                        frontier_auc=result.frontier_auc,
                        best_score=result.best_score,
                        success_rate=result.success_rate,
                        tokens=result.tokens,
                        wall_sec=time.monotonic() - started,
                        cost_usd=result.cost_usd,
                        integrity_passed=result.integrity_passed,
                        anti_cheat_passed=result.anti_cheat_passed,
                    )
                destination.append(result)

        def known_cost(results: list[PolicyArmResult]) -> float | None:
            costs = [result.cost_usd for result in results]
            known = [cost for cost in costs if cost is not None]
            return float(sum(known)) if len(known) == len(costs) else None

        evidence = PolicyReplayEvidence(
            snapshot_id=request.snapshot_id,
            seeds=request.seeds,
            champion_scores=tuple(result.frontier_auc for result in champion),
            challenger_scores=tuple(result.frontier_auc for result in challenger),
            champion_best_scores=tuple(result.best_score for result in champion),
            challenger_best_scores=tuple(result.best_score for result in challenger),
            champion_success_rates=tuple(result.success_rate for result in champion),
            challenger_success_rates=tuple(result.success_rate for result in challenger),
            champion_tokens=sum(result.tokens for result in champion),
            challenger_tokens=sum(result.tokens for result in challenger),
            champion_cost_usd=known_cost(champion),
            challenger_cost_usd=known_cost(challenger),
            champion_wall_sec=sum(result.wall_sec for result in champion),
            challenger_wall_sec=sum(result.wall_sec for result in challenger),
            champion_token_budget=request.token_budget_per_arm,
            challenger_token_budget=request.token_budget_per_arm,
            integrity_passed=all(result.integrity_passed for result in (*champion, *challenger)),
            anti_cheat_passed=all(result.anti_cheat_passed for result in (*champion, *challenger)),
            independent_executions=True,
        )
        evidence.validate_for(request)
        return evidence


class PolicyReplayExecutor(Protocol):
    """Production/test boundary for real paired policy execution."""

    def run_paired(self, request: PolicyReplayRequest) -> PolicyReplayEvidence:
        """Execute both arms independently on identical cases and budgets."""
        ...
