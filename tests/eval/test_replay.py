from __future__ import annotations

import pytest

from omnievolve.eval.replay import ReplayRecord, assert_deterministic_replay


def _record(score: float = 0.5) -> ReplayRecord:
    return ReplayRecord(
        candidate_hash="abc",
        evaluator_version_id="eval-v1",
        environment_version_id="env-v1",
        seed=7,
        split_name="hidden",
        score=score,
        metrics={"runtime": 1.0},
        passed=True,
    )


def test_replay_fingerprints_are_canonical_and_stable():
    first = _record()
    second = _record()
    assert first.input_fingerprint == second.input_fingerprint
    assert first.output_fingerprint == second.output_fingerprint
    assert_deterministic_replay(first, second)


def test_replay_rejects_output_drift():
    with pytest.raises(RuntimeError, match="non-deterministic"):
        assert_deterministic_replay(_record(), _record(0.6))
