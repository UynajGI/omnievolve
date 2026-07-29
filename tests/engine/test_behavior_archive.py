from __future__ import annotations

import random

import pytest

from omnievolve.engine.behavior_archive import (
    BehaviorArchive,
    derive_behavior_descriptor,
)

pytestmark = pytest.mark.unit


def test_descriptor_separates_recursive_and_iterative_programs():
    recursive = "def f(n):\n    return 1 if n <= 1 else n * f(n - 1)\n"
    iterative = "def f(xs):\n    for x in xs:\n        print(x)\n"

    assert derive_behavior_descriptor(recursive).structure == "recursive"
    assert derive_behavior_descriptor(iterative).structure == "iterative"


def test_archive_keeps_best_per_cell_and_never_crosses_islands():
    archive = BehaviorArchive(max_cells_per_island=4)
    code = "def f(xs):\n    for x in xs:\n        print(x)\n"
    assert archive.update(
        island_id="island_0", candidate_id="weak", score=0.4, code=code
    )
    assert archive.update(
        island_id="island_0", candidate_id="strong", score=0.8, code=code
    )
    assert not archive.update(
        island_id="island_0", candidate_id="worse", score=0.2, code=code
    )

    random.seed(3)
    assert archive.choose_parent("island_0", allowed_candidate_ids={"strong"}) == "strong"
    assert archive.choose_parent("island_1") is None


def test_archive_snapshot_round_trip_and_mismatch_fail_closed():
    archive = BehaviorArchive(max_cells_per_island=2)
    archive.update(
        island_id="island_0",
        candidate_id="c1",
        score=0.5,
        code="def f(x):\n    return x + 1\n",
    )
    restored = BehaviorArchive(max_cells_per_island=2)
    restored.restore_state(archive.snapshot_state())
    assert restored.snapshot_state() == archive.snapshot_state()

    with pytest.raises(ValueError, match="capacity"):
        BehaviorArchive(max_cells_per_island=3).restore_state(archive.snapshot_state())
