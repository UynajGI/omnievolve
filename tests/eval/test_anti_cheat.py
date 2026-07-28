from __future__ import annotations

import hashlib

from omnievolve.eval.anti_cheat import scan_candidate_source, verify_hidden_mounts
from omnievolve.sandbox.base import EvaluationPlan, MountSpec


def test_hidden_mount_digest_and_read_only_are_verified(tmp_path):
    hidden = tmp_path / "hidden_cases.json"
    hidden.write_text("secret", encoding="utf-8")
    digest = hashlib.sha256(hidden.read_bytes()).hexdigest()
    plan = EvaluationPlan(
        commands=[],
        mounts=[
            MountSpec(
                str(hidden),
                "/workspace/cases.json",
                visibility="hidden",
                integrity_sha256=digest,
            )
        ],
    )
    assert verify_hidden_mounts(plan) == []

    hidden.write_text("tampered", encoding="utf-8")
    assert verify_hidden_mounts(plan)[0].rule == "hidden_mount_digest_mismatch"


def test_candidate_evaluator_peeking_is_flagged():
    findings = scan_candidate_source("open('test_hidden.py').read()")
    assert {finding.rule for finding in findings} == {"forbidden_literal"}


def test_evaluator_contract_in_docstring_is_not_flagged():
    source = '''"""The evaluator owns hidden tests; candidate code must not inspect them."""
def solve(values):
    """Return values without reading test files."""
    return values
'''
    assert scan_candidate_source(source) == []


def test_normal_algorithm_is_not_flagged():
    assert scan_candidate_source("def sort(values): return sorted(values)") == []
