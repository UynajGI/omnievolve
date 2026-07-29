from __future__ import annotations

from dataclasses import replace

import pytest

from omnievolve.meta.governance import GovernancePolicy, L0PolicyMutator
from omnievolve.meta.policy_genome import SearchPolicyGenome
from omnievolve.meta.policy_runtime import (
    active_policy_fields,
    inactive_policy_fields,
    liveness_report,
    runtime_bindings,
    validate_policy_change,
)

pytestmark = pytest.mark.unit


def test_liveness_registry_covers_every_serialized_genome_field() -> None:
    bindings = runtime_bindings()

    assert set(bindings) == set(SearchPolicyGenome.__dataclass_fields__)
    assert active_policy_fields()
    assert inactive_policy_fields()
    for field_name in active_policy_fields():
        binding = bindings[field_name]
        assert binding.mutable is True
        assert binding.consumer
        assert binding.audit_event
    assert {item["field"] for item in liveness_report()} == set(bindings)


def test_inactive_field_is_frozen_for_mutation_and_canary() -> None:
    genome = SearchPolicyGenome()
    mutator = L0PolicyMutator(GovernancePolicy())

    mutated, reason = mutator.mutate(
        genome,
        "temperature_schedule",
        "cosine",
    )
    valid, inactive_changes = validate_policy_change(
        genome,
        replace(genome, temperature_schedule="cosine"),
    )

    assert mutated is None
    assert "inactive and frozen" in reason
    assert valid is False
    assert inactive_changes == ("temperature_schedule",)


def test_active_field_change_is_canary_eligible() -> None:
    genome = SearchPolicyGenome()

    valid, inactive_changes = validate_policy_change(
        genome,
        replace(genome, retrieval_budget=genome.retrieval_budget + 1),
    )

    assert valid is True
    assert inactive_changes == ()


def test_legacy_progressive_mcgs_snapshot_maps_to_lineage_ucb() -> None:
    with pytest.warns(DeprecationWarning, match="lineage_ucb"):
        genome = SearchPolicyGenome.from_dict(
            {
                "schema_version": 1,
                "parent_selector": "progressive_mcgs",
                "retrieval_budget": 7,
            }
        )

    assert genome.parent_selector == "lineage_ucb"
    assert genome.retrieval_budget == 7
    assert genome.to_dict()["schema_version"] == 2
