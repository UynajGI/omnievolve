from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "competition_campaign.py"
SPEC = importlib.util.spec_from_file_location("competition_campaign", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_checkpoint_generation_ignores_uncommitted_candidate_rows():
    experiment = {
        "checkpoint_data": '{"generation": 1, "total_candidates": 2}',
        "status": "completed",
    }

    assert MODULE._checkpoint_generation(experiment) == 1


def test_checkpoint_generation_handles_missing_or_invalid_data():
    assert MODULE._checkpoint_generation({"checkpoint_data": None}) == 0
    assert MODULE._checkpoint_generation({"checkpoint_data": "not-json"}) == 0


def _occam_row(generation: int, *, passed: bool, completed: bool = True) -> dict:
    return {
        "generation": generation,
        "eval_status": "completed" if completed else "running",
        "passed": passed,
        "primary_score": 1.0 if passed else 0.0,
        "metrics": {
            "min_train_acc": 1.0 if passed else 0.0,
            "min_test_acc": 1.0 if passed else 0.0,
        },
    }


def test_health_accepts_low_candidate_pass_rate_when_pipeline_is_complete():
    rows = [
        _occam_row(generation, passed=generation in {1, 3, 4, 8})
        for generation in range(1, 11)
    ]

    healthy, reasons = MODULE._health("occam", rows, generation=10)

    assert healthy is True
    assert reasons == []


def test_health_rejects_missing_or_incomplete_generation():
    rows = [_occam_row(generation, passed=True) for generation in range(1, 10)]
    rows.append(_occam_row(10, passed=False, completed=False))

    healthy, reasons = MODULE._health("occam", rows, generation=10)

    assert healthy is False
    assert any("generation" in reason for reason in reasons)
    assert any("未完成 evaluation" in reason for reason in reasons)
