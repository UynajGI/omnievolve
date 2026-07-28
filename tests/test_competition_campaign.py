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
