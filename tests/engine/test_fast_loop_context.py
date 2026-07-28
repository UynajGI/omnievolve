"""Task-context extraction tests for the fast evolution loop."""

import pytest

from omnievolve.engine.evolution_engine import EvolutionEngine
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
        params = None

        @staticmethod
        def fetchall(query, params):
            FakeDB.params = params
            return [
                {
                    "id": "bad-d",
                    "generation": 2,
                    "meta": '{"thought":"replace the squarer"}',
                    "passed": 0,
                    "primary_score": 0.0054,
                    "previous_best_score": 0.9954,
                    "metrics": (
                        '{"total_gates":460,"mystery-D_test_acc":0.0,'
                        '"mystery-D_bit_acc":0.875,"mystery-D_gates":182,'
                        '"behavior_signature":"same-output",'
                        '"mystery-D_first_test_failure":{"input":"0000",'
                        '"expected":"01","actual":"00","wrong_bits":[0]}}'
                    ),
                }
            ]

    class FakeEngine:
        _db = FakeDB()
        _experiment_id = "exp"

    summaries = FastLoopStep(FakeEngine())._load_sibling_summaries("island_0", 3)

    assert "passed=False" in summaries[0]
    assert "search_outcome=invalid" in summaries[0]
    assert "mystery-D_test_acc=0.0" in summaries[0]
    assert "mystery-D_bit_acc=0.875" in summaries[0]
    assert "behavior_signature=same-output" in summaries[0]
    assert "wrong_bits" in summaries[0]
    assert "mystery-D_gates=182" in summaries[0]
    assert "replace the squarer" in summaries[0]
    assert FakeDB.params[-1] == 0


def test_sibling_summary_marks_correct_plateau_as_no_improvement():
    class FakeDB:
        @staticmethod
        def fetchall(query, params):
            return [
                {
                    "id": "plateau",
                    "generation": 7,
                    "meta": '{"thought":"repeat the same multiplier tree"}',
                    "passed": 1,
                    "primary_score": 0.99601,
                    "previous_best_score": 0.99601,
                    "metrics": '{"total_gates":399}',
                }
            ]

    class FakeEngine:
        _db = FakeDB()
        _experiment_id = "exp"

    summaries = FastLoopStep(FakeEngine())._load_sibling_summaries("island_0", 8)

    assert "passed=True" in summaries[0]
    assert "search_outcome=no_improvement" in summaries[0]
    assert "repeat the same multiplier tree" in summaries[0]


def test_failed_direction_memory_keeps_structured_outcome_and_ten_entries():
    class State:
        _failed_directions = []
        _meta_scratchpad = ""

    state = State()
    for index in range(12):
        EvolutionEngine._update_meta_scratchpad(
            state,
            f"rewrite squarer attempt {index} with a long structural explanation",
            0.006,
            failure_summary=f"mystery-D:test_acc=0.0,gates={120 + index}",
        )

    assert len(state._failed_directions) == 10
    assert "mystery-D:test_acc=0.0,gates=131" in state._meta_scratchpad
    assert "attempted_direction=rewrite squarer attempt 11" in state._meta_scratchpad
