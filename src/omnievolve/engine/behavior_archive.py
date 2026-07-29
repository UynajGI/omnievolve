"""Minimal behavior-cell archive for independently ablatable QD search.

The archive deliberately remains smaller than a full MAP-Elites rewrite.  It
stores one elite per interpretable behavior cell, scoped by island, and can
occasionally contribute a parent to the existing search controller.
"""

from __future__ import annotations

import ast
import math
import random
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class BehaviorDescriptor:
    """Coarse, task-agnostic behavior descriptor for a Python candidate."""

    structure: str
    size_bin: int
    runtime_bin: int

    @property
    def cell_key(self) -> str:
        return f"{self.structure}:{self.size_bin}:{self.runtime_bin}"


@dataclass(frozen=True)
class BehaviorElite:
    candidate_id: str
    score: float
    descriptor: BehaviorDescriptor


def derive_behavior_descriptor(
    code: str,
    metrics: dict[str, Any] | None = None,
) -> BehaviorDescriptor:
    """Derive stable, auditable behavior features without an embedding model."""

    metrics = metrics or {}
    nonblank_lines = sum(1 for line in code.splitlines() if line.strip())
    size_bin = min(8, int(math.log2(max(1, nonblank_lines))))

    runtime_ms = 0.0
    for key in (
        "median_execution_time_ms",
        "execution_time_ms",
        "runtime_ms",
        "wall_time_ms",
    ):
        value = metrics.get(key)
        if isinstance(value, (int, float)) and math.isfinite(float(value)):
            runtime_ms = max(0.0, float(value))
            break
    runtime_bin = min(12, int(math.log2(max(1.0, runtime_ms))))

    try:
        tree = ast.parse(code)
    except SyntaxError:
        return BehaviorDescriptor("unparsed", size_bin, runtime_bin)

    function_names = {
        node.name for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    called_names = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    imported_roots = {
        alias.asname or alias.name.split(".", 1)[0]
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }

    if function_names & called_names:
        structure = "recursive"
    elif imported_roots & {"numpy", "np", "jax", "torch", "numba"}:
        structure = "vectorized"
    elif any(isinstance(node, (ast.For, ast.While, ast.AsyncFor)) for node in ast.walk(tree)):
        structure = "iterative"
    elif any(
        isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp))
        for node in ast.walk(tree)
    ):
        structure = "comprehension"
    elif any(isinstance(node, (ast.If, ast.Match)) for node in ast.walk(tree)):
        structure = "branching"
    else:
        structure = "straight_line"

    return BehaviorDescriptor(structure, size_bin, runtime_bin)


class BehaviorArchive:
    """Bounded island-local grid archive with deterministic snapshot support."""

    def __init__(self, *, max_cells_per_island: int = 128) -> None:
        if max_cells_per_island <= 0:
            raise ValueError("max_cells_per_island must be positive")
        self._max_cells = max_cells_per_island
        self._cells: dict[str, dict[str, BehaviorElite]] = {}

    def update(
        self,
        *,
        island_id: str,
        candidate_id: str,
        score: float,
        code: str,
        metrics: dict[str, Any] | None = None,
    ) -> bool:
        """Insert or improve a cell; return whether the archive changed."""

        descriptor = derive_behavior_descriptor(code, metrics)
        cells = self._cells.setdefault(island_id, {})
        current = cells.get(descriptor.cell_key)
        proposed = BehaviorElite(candidate_id, float(score), descriptor)
        if current is not None:
            if proposed.score < current.score:
                return False
            if proposed.score == current.score and proposed.candidate_id >= current.candidate_id:
                return False
            cells[descriptor.cell_key] = proposed
            return True

        if len(cells) >= self._max_cells:
            weakest_key, weakest = min(
                cells.items(),
                key=lambda item: (item[1].score, item[1].candidate_id),
            )
            if proposed.score <= weakest.score:
                return False
            del cells[weakest_key]
        cells[descriptor.cell_key] = proposed
        return True

    def choose_parent(
        self,
        island_id: str,
        *,
        allowed_candidate_ids: Iterable[str] | None = None,
    ) -> str | None:
        """Uniformly sample occupied behavior cells within one island."""

        allowed = set(allowed_candidate_ids) if allowed_candidate_ids is not None else None
        entries = [
            elite
            for elite in self._cells.get(island_id, {}).values()
            if allowed is None or elite.candidate_id in allowed
        ]
        if not entries:
            return None
        entries.sort(key=lambda elite: (elite.descriptor.cell_key, elite.candidate_id))
        return random.choice(entries).candidate_id

    def get_stats(self) -> dict[str, Any]:
        return {
            "max_cells_per_island": self._max_cells,
            "islands": {
                island_id: {
                    "occupied_cells": len(cells),
                    "best_score": max((elite.score for elite in cells.values()), default=None),
                }
                for island_id, cells in sorted(self._cells.items())
            },
        }

    def snapshot_state(self) -> dict[str, Any]:
        return {
            "max_cells_per_island": self._max_cells,
            "cells": {
                island_id: {
                    key: {
                        "candidate_id": elite.candidate_id,
                        "score": elite.score,
                        "descriptor": asdict(elite.descriptor),
                    }
                    for key, elite in sorted(cells.items())
                }
                for island_id, cells in sorted(self._cells.items())
            },
        }

    def restore_state(self, state: dict[str, Any] | None) -> None:
        if not state:
            return
        if int(state.get("max_cells_per_island", -1)) != self._max_cells:
            raise ValueError("behavior archive checkpoint capacity does not match runtime")
        restored: dict[str, dict[str, BehaviorElite]] = {}
        for island_id, cells in state.get("cells", {}).items():
            restored[str(island_id)] = {}
            for key, payload in cells.items():
                descriptor = BehaviorDescriptor(**payload["descriptor"])
                if descriptor.cell_key != key:
                    raise ValueError("behavior archive checkpoint contains an invalid cell key")
                restored[str(island_id)][str(key)] = BehaviorElite(
                    candidate_id=str(payload["candidate_id"]),
                    score=float(payload["score"]),
                    descriptor=descriptor,
                )
        self._cells = restored
