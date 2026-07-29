from __future__ import annotations

import pytest

from omnievolve.meta.policy_genome import SearchPolicyGenome
from omnievolve.meta.policy_replay import (
    PolicyArmResult,
    PolicyCanaryRunner,
    PolicyReplayEvidence,
    PolicyReplayRequest,
)


def _request() -> PolicyReplayRequest:
    return PolicyReplayRequest(
        experiment_id="exp",
        champion_policy_id="champ",
        challenger_policy_id="challenger",
        champion=SearchPolicyGenome(),
        challenger=SearchPolicyGenome(retrieval_budget=9),
        snapshot_id="snapshot-sha256",
        seeds=(11, 22, 33),
        token_budget_per_arm=1_000,
        wall_budget_sec_per_arm=30.0,
    )


def test_equal_budget_evidence_validates() -> None:
    request = _request()
    evidence = PolicyReplayEvidence(
        snapshot_id=request.snapshot_id,
        seeds=request.seeds,
        champion_scores=(0.5, 0.6, 0.7),
        challenger_scores=(0.6, 0.7, 0.8),
        champion_tokens=900,
        challenger_tokens=950,
    )
    evidence.validate_for(request)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("snapshot_id", "other", "snapshot"),
        ("seeds", (11, 22), "seeds"),
        ("independent_executions", False, "independent"),
        ("challenger_tokens", 1_001, "token budget"),
    ],
)
def test_replay_evidence_fails_closed(field: str, value: object, message: str) -> None:
    request = _request()
    values = {
        "snapshot_id": request.snapshot_id,
        "seeds": request.seeds,
        "champion_scores": (0.5, 0.6, 0.7),
        "challenger_scores": (0.6, 0.7, 0.8),
        "champion_tokens": 900,
        "challenger_tokens": 950,
        "independent_executions": True,
    }
    values[field] = value
    evidence = PolicyReplayEvidence(**values)
    with pytest.raises(ValueError, match=message):
        evidence.validate_for(request)


def test_policy_canary_runs_independent_paired_arms_in_alternating_order() -> None:
    calls: list[tuple[int, str, str]] = []

    class ArmRunner:
        def run_arm(self, *, request, policy, policy_id, seed, arm):
            calls.append((seed, arm, policy_id))
            return PolicyArmResult(
                frontier_auc=0.5 + policy.retrieval_budget / 100,
                best_score=0.8,
                success_rate=1.0,
                tokens=100,
                wall_sec=0.1,
                cost_usd=0.01,
            )

    evidence = PolicyCanaryRunner(ArmRunner()).run_paired(_request())

    assert calls == [
        (11, "champion", "champ"),
        (11, "challenger", "challenger"),
        (22, "challenger", "challenger"),
        (22, "champion", "champ"),
        (33, "champion", "champ"),
        (33, "challenger", "challenger"),
    ]
    assert evidence.independent_executions is True
    assert evidence.champion_tokens == evidence.challenger_tokens == 300
    assert all(
        challenger > champion
        for champion, challenger in zip(
            evidence.champion_scores,
            evidence.challenger_scores,
            strict=True,
        )
    )
