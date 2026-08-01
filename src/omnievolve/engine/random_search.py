"""Deterministic, LLM-free random-search mutations for research baselines."""

from __future__ import annotations

import ast
import hashlib
import random
from dataclasses import dataclass


@dataclass(frozen=True)
class RandomMutation:
    """A syntax-valid random mutation and its replayable description."""

    code: str
    description: str
    seed: int


def derive_random_search_seed(
    *,
    experiment_seed: int,
    generation: int,
    slot: int,
    island_id: str,
    parent_code: str,
) -> int:
    """Derive a stable per-slot seed without depending on thread scheduling."""
    payload = (f"{experiment_seed}\0{generation}\0{slot}\0{island_id}\0{parent_code}").encode()
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")


def mutate_randomly(source: str, *, seed: int) -> RandomMutation:
    """Apply one uniformly sampled AST mutation and return parseable Python.

    This is task-agnostic and does not inspect evaluation feedback. It provides
    a genuine random-search baseline rather than an LLM agent with random parent
    selection.
    """
    tree = ast.parse(source)
    rng = random.Random(seed)
    sites: list[tuple[str, ast.AST]] = []

    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, int | float)
            and not isinstance(node.value, bool)
        ):
            sites.append(("numeric_constant", node))
        elif isinstance(node, ast.Compare) and node.ops:
            if any(
                isinstance(op, ast.Lt | ast.LtE | ast.Gt | ast.GtE | ast.Eq | ast.NotEq)
                for op in node.ops
            ):
                sites.append(("comparison_operator", node))
        elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add | ast.Sub):
            sites.append(("arithmetic_operator", node))
        elif isinstance(node, ast.BoolOp):
            sites.append(("boolean_operator", node))

    if not sites:
        nonce_name = f"_random_search_nonce_{seed:016x}"
        tree.body.append(
            ast.Assign(
                targets=[ast.Name(id=nonce_name, ctx=ast.Store())],
                value=ast.Constant(value=seed),
            )
        )
        description = f"append deterministic nonce {nonce_name}"
    else:
        kind, node = rng.choice(sites)
        description = _mutate_site(kind, node, rng)

    ast.fix_missing_locations(tree)
    code = ast.unparse(tree).rstrip() + "\n"
    ast.parse(code)
    return RandomMutation(code=code, description=description, seed=seed)


def _mutate_site(kind: str, node: ast.AST, rng: random.Random) -> str:
    if kind == "numeric_constant":
        assert isinstance(node, ast.Constant)
        old_value = node.value
        assert isinstance(old_value, int | float) and not isinstance(old_value, bool)
        if isinstance(old_value, int):
            node.value = old_value + rng.choice((-2, -1, 1, 2))
        else:
            node.value = old_value * rng.choice((0.5, 0.8, 1.2, 2.0))
        return f"numeric constant {old_value!r} -> {node.value!r}"

    if kind == "comparison_operator":
        assert isinstance(node, ast.Compare)
        index = rng.randrange(len(node.ops))
        compare_old_op = node.ops[index]
        replacements: dict[type[ast.cmpop], type[ast.cmpop]] = {
            ast.Lt: ast.LtE,
            ast.LtE: ast.Lt,
            ast.Gt: ast.GtE,
            ast.GtE: ast.Gt,
            ast.Eq: ast.NotEq,
            ast.NotEq: ast.Eq,
        }
        replacement = replacements.get(type(compare_old_op))
        if replacement is None:
            return "comparison operator unchanged"
        node.ops[index] = replacement()
        return f"comparison {type(compare_old_op).__name__} -> {replacement.__name__}"

    if kind == "arithmetic_operator":
        assert isinstance(node, ast.BinOp)
        arithmetic_old_type = type(node.op)
        node.op = ast.Sub() if isinstance(node.op, ast.Add) else ast.Add()
        return f"arithmetic {arithmetic_old_type.__name__} -> {type(node.op).__name__}"

    assert kind == "boolean_operator"
    assert isinstance(node, ast.BoolOp)
    boolean_old_type = type(node.op)
    node.op = ast.Or() if isinstance(node.op, ast.And) else ast.And()
    return f"boolean {boolean_old_type.__name__} -> {type(node.op).__name__}"
