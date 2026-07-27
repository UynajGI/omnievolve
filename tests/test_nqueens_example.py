"""N-queens example baseline regression tests."""

from __future__ import annotations

import json

import pytest

from examples.nqueens.initial_code import contract_nqueens, main

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("n", "expected"),
    [
        (0, 1),
        (1, 1),
        (2, 0),
        (3, 0),
        (4, 2),
        (5, 10),
        (6, 4),
        (7, 40),
        (8, 92),
    ],
)
def test_exact_seed_matches_known_counts(n: int, expected: int) -> None:
    assert contract_nqueens(n) == expected


def test_negative_size_is_rejected() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        contract_nqueens(-1)


def test_main_writes_candidate_result(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("NQUEENS_N", "8")

    main()

    result = json.loads((tmp_path / "candidate_result.json").read_text(encoding="utf-8"))
    assert result["n"] == 8
    assert result["q_n"] == 92
    assert result["method"] == "exact_bitmask_backtracking"
