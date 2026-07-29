from __future__ import annotations

import pytest

from omnievolve.engine.operator_portfolio import OperatorPortfolio

pytestmark = pytest.mark.unit


def test_ucb_explores_eligible_operators_and_uses_relative_gain():
    portfolio = OperatorPortfolio(algorithm="ucb", operators=("point", "rewrite"))
    first = portfolio.select(task="sort", stage="normal", eligible=("point", "rewrite"))
    assert first.operator == "point"
    portfolio.update(first, relative_gain=-0.5, passed=True)

    second = portfolio.select(task="sort", stage="normal", eligible=("point", "rewrite"))
    assert second.operator == "rewrite"
    portfolio.update(second, relative_gain=0.5, passed=True)

    state = portfolio.snapshot_state()["state"]["sort\x1fnormal"]
    assert state["rewrite"]["reward_sum"] > state["point"]["reward_sum"]


def test_ineligible_operator_is_never_selected():
    portfolio = OperatorPortfolio(operators=("point", "crossover"))
    decision = portfolio.select(task="sort", stage="normal", eligible=("point",))
    assert decision.operator == "point"


def test_snapshot_round_trip_and_algorithm_mismatch_fail_closed():
    portfolio = OperatorPortfolio(algorithm="thompson")
    decision = portfolio.select(task="sort", stage="stagnant", eligible=("repair",))
    portfolio.update(decision, relative_gain=0.2, passed=True)

    restored = OperatorPortfolio(algorithm="thompson")
    restored.restore_state(portfolio.snapshot_state())
    assert restored.snapshot_state() == portfolio.snapshot_state()

    with pytest.raises(ValueError, match="algorithm"):
        OperatorPortfolio(algorithm="ucb").restore_state(portfolio.snapshot_state())
