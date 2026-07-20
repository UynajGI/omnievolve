"""Agent 基类与 Protocol.

S5-01: 冻结 AgentContext/ThoughtOutput/CodeOutput
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class AgentContext:
    """Agent 上下文."""

    experiment_id: str
    task_id: str
    generation: int
    island_id: str | None = None
    parent_candidate_ids: list[str] = field(default_factory=list)
    parent_thoughts: list[str] = field(default_factory=list)
    parent_artifact_hashes: list[str] = field(default_factory=list)
    # ShinkaEvolve/AlphaEvolve pattern: inspiration programs (diverse high-scorers
    # + random samples, distinct from direct parents) provide exemplars for
    # creative recombination.
    inspiration_programs: list[dict] = field(default_factory=list)
    memory_hits: list[dict] = field(default_factory=list)
    domain_hints: list[str] = field(default_factory=list)
    # ShinkaEvolve meta-scratchpad: accumulates global insights across generations
    # (e.g., "X direction consistently fails"), separate from per-candidate thoughts.
    meta_scratchpad: str = ""
    search_policy_id: str = "default"
    evaluator_version_id: str = ""
    environment_version_id: str = ""
    prompt_version_id: str = ""
    system_prompt: str = ""
    model: str = ""
    provenance: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ThoughtOutput:
    """思想输出."""

    thought: str
    rationale: str
    risk_notes: str = ""
    confidence: float = 0.5
    mechanism_tags: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class CodeOutput:
    """代码输出."""

    diff: str
    full_code: str
    explanation: str = ""
    touched_files: list[str] = field(default_factory=list)


@runtime_checkable
class DirectorAgent(Protocol):
    """Director Agent Protocol - 思想进化."""

    def evolve_thought(self, ctx: AgentContext) -> ThoughtOutput:
        """进化思想."""
        ...


@runtime_checkable
class CoderAgent(Protocol):
    """Coder Agent Protocol - 代码生成."""

    def generate_code(self, ctx: AgentContext, thought: ThoughtOutput) -> CodeOutput:
        """生成代码."""
        ...


@runtime_checkable
class CriticAgent(Protocol):
    """Critic Agent Protocol - 静态审查."""

    def review(self, code: CodeOutput, thought: ThoughtOutput) -> tuple[bool, str]:
        """审查代码.

        Returns:
            (passed, feedback)
        """
        ...


@runtime_checkable
class MetaAgent(Protocol):
    """Meta Agent Protocol - 策略优化."""

    def optimize(
        self,
        health: dict,
        champion_policy: dict,
        history: list[dict],
    ) -> list[dict]:
        """提出优化动作."""
        ...
