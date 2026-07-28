"""Task-context extraction tests for the fast evolution loop."""

import pytest

from omnievolve.engine.fast_loop import FastLoopStep, _extract_domain_hint

pytestmark = pytest.mark.unit


def test_extract_domain_hint_uses_module_contract():
    code = '"""Optimize LJ38 while preserving candidate_result.json."""\nVALUE = 1\n'

    hint = _extract_domain_hint(code, "initial_code")

    assert hint == "Optimize LJ38 while preserving candidate_result.json."
    assert "initial_code" not in hint


def test_extract_domain_hint_falls_back_for_invalid_code():
    assert _extract_domain_hint("def broken(", "lennard_jones") == "lennard_jones"


def test_sibling_summary_includes_failure_metrics():
    class FakeDB:
        @staticmethod
        def fetchall(query, params):
            return [
                {
                    "id": "bad-d",
                    "generation": 2,
                    "meta": '{"thought":"replace the squarer"}',
                    "passed": 0,
                    "primary_score": 0.0054,
                    "metrics": (
                        '{"total_gates":460,"mystery-D_test_acc":0.0,'
                        '"mystery-D_gates":182}'
                    ),
                }
            ]

    class FakeEngine:
        _db = FakeDB()
        _experiment_id = "exp"

    summaries = FastLoopStep(FakeEngine())._load_sibling_summaries("island_0", 3)

    assert "passed=False" in summaries[0]
    assert "mystery-D_test_acc=0.0" in summaries[0]
    assert "mystery-D_gates=182" in summaries[0]
    assert "replace the squarer" in summaries[0]
