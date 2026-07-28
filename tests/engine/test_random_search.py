"""LLM-free random-search baseline tests."""

from __future__ import annotations

import ast

import pytest

from omnievolve.config import OmniEvolveSettings, build_evolution_config
from omnievolve.engine.random_search import (
    derive_random_search_seed,
    mutate_randomly,
)
from omnievolve.research.matrix import DEFAULT_VARIANTS

pytestmark = pytest.mark.unit


SOURCE = """
def sort_items(values):
    for index in range(1, len(values)):
        if values[index] < values[index - 1]:
            values[index], values[index - 1] = values[index - 1], values[index]
    return values
"""


def test_random_mutation_is_deterministic_and_parseable():
    first = mutate_randomly(SOURCE, seed=123)
    replay = mutate_randomly(SOURCE, seed=123)

    assert first == replay
    assert first.code != SOURCE
    ast.parse(first.code)


def test_random_mutation_explores_multiple_syntax_variants():
    mutations = {mutate_randomly(SOURCE, seed=seed).code for seed in range(20)}

    assert len(mutations) >= 4
    for code in mutations:
        ast.parse(code)


def test_random_mutation_falls_back_to_replayable_nonce():
    mutation = mutate_randomly("def identity(value):\n    return value\n", seed=7)

    assert "_random_search_nonce_" in mutation.code
    ast.parse(mutation.code)


def test_random_search_seed_is_slot_stable():
    kwargs = {
        "experiment_seed": 42,
        "generation": 3,
        "island_id": "island_0",
        "parent_code": SOURCE,
    }

    assert derive_random_search_seed(slot=0, **kwargs) == derive_random_search_seed(
        slot=0, **kwargs
    )
    assert derive_random_search_seed(slot=0, **kwargs) != derive_random_search_seed(
        slot=1, **kwargs
    )


def test_random_search_variant_enables_llm_free_engine_path():
    variant = next(item for item in DEFAULT_VARIANTS if item.name == "random_search")
    settings = OmniEvolveSettings()
    settings.evolution.random_search_mode = True

    assert variant.config_overrides["evolution.random_search_mode"] is True
    assert build_evolution_config(settings).random_search_mode is True
