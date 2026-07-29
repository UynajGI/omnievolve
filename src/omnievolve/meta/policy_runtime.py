"""Runtime liveness registry for :class:`SearchPolicyGenome`.

Slow-loop mutations are only meaningful when a field has a named runtime
consumer and an observable audit signal.  The registry is deliberately
explicit: adding a genome field without registering its effect leaves it
frozen rather than silently expanding the search space with a dead gene.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

PolicyFieldStatus = Literal["active", "inactive", "deprecated"]


@dataclass(frozen=True)
class PolicyRuntimeBinding:
    """One genome field's runtime contract."""

    field_name: str
    status: PolicyFieldStatus
    consumer: str | None
    audit_event: str | None
    reason: str = ""

    @property
    def mutable(self) -> bool:
        return self.status == "active" and bool(self.consumer and self.audit_event)


_ACTIVE: dict[str, tuple[str, str]] = {
    "parent_selector": ("EvolutionEngine._select_parents", "parent_selection"),
    "retrieval_budget": ("FastLoopStep.prepare", "memory_retrieval"),
    "model_routing_policy": ("ModelRouter", "model_route"),
    "director_prompt_version": ("Director.evolve_thought", "llm_call_ledger"),
    "coder_prompt_version": ("Coder.generate_code", "llm_call_ledger"),
    "epiplexity_beta": ("FastLoopStep._execute_sandbox", "search_objectives"),
}

_INACTIVE_REASONS: dict[str, str] = {
    "mutation_mix": "operator bandit is a separate post-baseline experiment",
    "crossover_policy": "runtime crossover vocabulary is not schema-compatible yet",
    "memory_scope_weights": "memory retrieval does not expose weighted scopes",
    "context_pruning_policy": "ContextBuilder has no policy dispatch contract",
    "novelty_policy": "novelty semantics are evaluation-governed, not self-mutable",
    "critic_prompt_version": "static/LLM critic prompt routing is not version-bound",
    "temperature_schedule": "agents do not consume a shared temperature scheduler",
    "island_migration_policy": "only audited periodic migration is implemented",
    "backtracking_policy": "no replayable backtracking runtime exists",
}


def runtime_bindings() -> dict[str, PolicyRuntimeBinding]:
    """Return a copy of the complete liveness registry."""
    from omnievolve.meta.policy_genome import SearchPolicyGenome

    bindings: dict[str, PolicyRuntimeBinding] = {}
    for field_name in SearchPolicyGenome.__dataclass_fields__:
        if field_name in _ACTIVE:
            consumer, event = _ACTIVE[field_name]
            bindings[field_name] = PolicyRuntimeBinding(
                field_name=field_name,
                status="active",
                consumer=consumer,
                audit_event=event,
            )
        else:
            bindings[field_name] = PolicyRuntimeBinding(
                field_name=field_name,
                status="inactive",
                consumer=None,
                audit_event=None,
                reason=_INACTIVE_REASONS.get(field_name, "no registered runtime effect"),
            )
    return bindings


def active_policy_fields() -> frozenset[str]:
    """Fields that may be mutated or compared by a policy canary."""
    return frozenset(
        field_name for field_name, binding in runtime_bindings().items() if binding.mutable
    )


def inactive_policy_fields() -> frozenset[str]:
    """Serialized compatibility fields that are frozen at runtime."""
    return frozenset(runtime_bindings()) - active_policy_fields()


def validate_policy_change(
    before: object,
    after: object,
) -> tuple[bool, tuple[str, ...]]:
    """Reject challenger changes to fields without a live runtime contract."""
    inactive_changes = tuple(
        field_name
        for field_name in sorted(inactive_policy_fields())
        if getattr(before, field_name, None) != getattr(after, field_name, None)
    )
    return not inactive_changes, inactive_changes


def liveness_report() -> list[dict[str, object]]:
    """Machine-readable audit report used by CLI/tests/research provenance."""
    return [
        {
            "field": binding.field_name,
            "status": binding.status,
            "mutable": binding.mutable,
            "consumer": binding.consumer,
            "audit_event": binding.audit_event,
            "reason": binding.reason,
        }
        for binding in runtime_bindings().values()
    ]


__all__ = [
    "PolicyRuntimeBinding",
    "active_policy_fields",
    "inactive_policy_fields",
    "liveness_report",
    "runtime_bindings",
    "validate_policy_change",
]
