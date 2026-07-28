"""Deterministic, fail-closed checks for common evaluator-peeking attacks."""

from __future__ import annotations

import ast
import hashlib
from dataclasses import dataclass
from pathlib import Path

from omnievolve.sandbox.base import EvaluationPlan


@dataclass(frozen=True)
class AntiCheatFinding:
    rule: str
    detail: str


def verify_hidden_mounts(plan: EvaluationPlan) -> list[AntiCheatFinding]:
    """Verify hidden inputs are immutable and match their declared digest."""
    findings: list[AntiCheatFinding] = []
    for mount in plan.mounts:
        if mount.visibility != "hidden":
            continue
        if not mount.read_only:
            findings.append(AntiCheatFinding("hidden_mount_writable", mount.target))
        if mount.integrity_sha256:
            path = Path(mount.source)
            if not path.is_file():
                findings.append(AntiCheatFinding("hidden_mount_missing", mount.target))
                continue
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
            if actual != mount.integrity_sha256:
                findings.append(AntiCheatFinding("hidden_mount_digest_mismatch", mount.target))
    return findings


def scan_candidate_source(source: str) -> list[AntiCheatFinding]:
    """Flag explicit attempts to inspect tests, evaluators, or hidden files."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    findings: list[AntiCheatFinding] = []
    forbidden_fragments = (
        "test_",
        "hidden",
        "evaluator",
        "benchmark_result",
        "/proc/",
        "__pycache__",
    )
    filesystem_calls = {"open", "listdir", "scandir", "walk", "glob", "rglob"}
    # Documentation commonly describes the evaluator contract or hidden-test
    # threat model.  A docstring is not executed and must not make an otherwise
    # valid candidate fail closed.  Runtime string literals remain scanned.
    docstring_nodes: set[int] = set()
    for owner in ast.walk(tree):
        if not isinstance(owner, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if (
            owner.body
            and isinstance(owner.body[0], ast.Expr)
            and isinstance(owner.body[0].value, ast.Constant)
            and isinstance(owner.body[0].value.value, str)
        ):
            docstring_nodes.add(id(owner.body[0].value))

    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) in docstring_nodes:
                continue
            value = node.value.lower()
            if any(fragment in value for fragment in forbidden_fragments):
                findings.append(AntiCheatFinding("forbidden_literal", node.value[:120]))
        if isinstance(node, ast.Call):
            name = ""
            if isinstance(node.func, ast.Name):
                name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                name = node.func.attr
            if name in filesystem_calls and not node.args:
                findings.append(AntiCheatFinding("filesystem_discovery", name))
    return findings
