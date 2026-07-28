"""Reference-edge credit assignment tests."""

from __future__ import annotations

import pytest

from omnievolve.engine.mcts import ProgressiveMCGS

pytestmark = pytest.mark.unit


def test_reference_credit_updates_beta_without_fake_visits():
    search = ProgressiveMCGS()
    search.add_node("root")
    search.add_node("leaf", parent="root")
    reference = search.add_node("reference")

    search.backpropagate("leaf", 0.8)
    credited = search.credit_references(
        ["reference", "reference"],
        0.8,
        weight=0.25,
        exclude_ids={"leaf", "root"},
    )

    assert credited == ["reference"]
    assert reference.visit_count == 0
    assert reference.value_sum == 0.0
    assert reference.alpha == pytest.approx(1.2)
    assert reference.beta == pytest.approx(1.05)


def test_reference_credit_skips_tree_path_and_unknown_nodes():
    search = ProgressiveMCGS()
    root = search.add_node("root")
    search.add_node("leaf", parent="root")

    credited = search.credit_references(
        ["root", "missing"],
        1.0,
        exclude_ids={"root", "leaf"},
    )

    assert credited == []
    assert root.alpha == 1.0
    assert root.beta == 1.0
