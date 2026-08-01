from __future__ import annotations

import pytest

from omnievolve.agents.base import AgentContext, ThoughtOutput
from omnievolve.agents.coder import Coder, GenerationMode

pytestmark = pytest.mark.unit


def test_operator_directive_overrides_legacy_stagnation_mode():
    ctx = AgentContext(
        experiment_id="exp",
        task_id="sort",
        generation=1,
        stagnation_level=3,
        generation_mode="point",
    )

    assert Coder._select_mode(ctx) == GenerationMode.TARGETED_DIFF


def test_rewrite_and_crossover_map_to_distinct_generation_modes():
    base = AgentContext(experiment_id="exp", task_id="sort", generation=1)

    assert (
        Coder._select_mode(AgentContext(**{**base.__dict__, "generation_mode": "rewrite"}))
        == GenerationMode.FULL_REWRITE
    )
    assert (
        Coder._select_mode(AgentContext(**{**base.__dict__, "generation_mode": "crossover"}))
        == GenerationMode.FUSION_AWARE
    )


def test_repair_operator_changes_coder_instruction():
    coder = Coder(object())  # type: ignore[arg-type]
    ctx = AgentContext(
        experiment_id="exp",
        task_id="sort",
        generation=1,
        generation_mode="repair",
    )
    thought = ThoughtOutput("fix it", "repair a failing candidate")

    message = coder._build_user_message(ctx, thought)

    assert "Treat this as a repair operator" in message
