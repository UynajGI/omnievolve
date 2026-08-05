"""2.4 离散集成 tie-breaker 测试（logprobs-free）.

改进计划 §2.4 — 任务分数打平时用 K 次 A/B 成对比较聚合偏好，
给 search_score 加有界 bonus；不触碰 passed/primary_score。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from omnievolve.agents.llm_gateway import FakeLLM
from omnievolve.engine.fast_loop import FastLoopStep
from omnievolve.engine.tie_breaker import DiscreteTieBreaker
from omnievolve.eval.task_evaluator import EvalOutput

pytestmark = pytest.mark.unit


def _breaker(llm=None, **kwargs) -> DiscreteTieBreaker:
    defaults = dict(model="", tolerance=0.01, repetitions=3, bonus_cap=0.01)
    defaults.update(kwargs)
    return DiscreteTieBreaker(llm or FakeLLM(responses=["A"]), **defaults)


class TestTieBreakerUnit:
    def test_is_tie(self):
        b = _breaker()
        assert b.is_tie(0.5, 0.505)  # |Δ|=0.005 ≤ 0.01
        assert b.is_tie(0.5, 0.5099)  # 接近边界、明确在容差内
        assert not b.is_tie(0.5, 0.52)  # 明确超出

    def test_majority_prefers_child(self):
        # 3 次比较，child 2 票（含一次位置交换回映射），parent 1 票 → majority child
        llm = FakeLLM(responses=["B", "A", "A"])
        b = _breaker(llm)
        outcome = b.break_tie(
            task="t",
            code_a="parent code",
            code_b="child code",
            score_a=0.5,
            score_b=0.505,
        )
        assert outcome.preferred == "b"
        assert outcome.b_wins == 2
        assert outcome.a_wins == 1
        assert outcome.bonus > 0
        assert outcome.bonus <= 0.01  # 有界

    def test_position_swap_maps_labels_back(self):
        # a_first=False 时提示中 A 标签实指 code_b（child）；
        # 响应 "A" 应回映射为 b。
        llm = FakeLLM(responses=["B", "A", "B"])
        b = _breaker(llm)
        # index 0: a_first → "B"=b；index 1: b_first → "A"=b(child)；
        # index 2: a_first → "B"=b → 3:0 child
        outcome = b.break_tie(
            task="t",
            code_a="parent",
            code_b="child",
            score_a=0.5,
            score_b=0.5,
        )
        assert outcome.a_wins == 0
        assert outcome.b_wins == 3
        assert outcome.preferred == "b"

    def test_no_majority_yields_zero_bonus(self):
        # 2 次比较各投一票（位置交换回映射后平局）→ 无多数，bonus=0
        llm = FakeLLM(responses=["A", "A"])
        b = _breaker(llm, repetitions=2)
        outcome = b.break_tie(
            task="t",
            code_a="parent",
            code_b="child",
            score_a=0.5,
            score_b=0.5,
        )
        assert outcome.a_wins == 1
        assert outcome.b_wins == 1
        assert outcome.preferred is None
        assert outcome.bonus == 0.0

    def test_invalid_responses_count_as_invalid(self):
        llm = FakeLLM(responses=["maybe A is better", "not sure", "B"])
        b = _breaker(llm)
        outcome = b.break_tie(
            task="t",
            code_a="p",
            code_b="c",
            score_a=0.5,
            score_b=0.5,
        )
        # "maybe A is better" 含 A → 计 a；"not sure" 无 A/B → invalid
        assert outcome.invalid == 1
        assert outcome.total == 3

    def test_bonus_scales_with_win_ratio_and_caps(self):
        # 全票投 child 需交替响应（位置交换回映射）→ bonus = cap × 1.0
        llm = FakeLLM(responses=["B", "A", "B"])
        b = _breaker(llm, bonus_cap=0.02)
        outcome = b.break_tie(
            task="t",
            code_a="p",
            code_b="c",
            score_a=0.5,
            score_b=0.5,
        )
        assert outcome.b_wins == 3
        assert outcome.bonus == pytest.approx(0.02)  # 全票 → cap
        assert outcome.bonus <= 0.02  # 有界


class _EngineStub:
    """_apply_tie_break_bonus 的最小 engine 代理."""

    def __init__(self, tie_breaker, *, task_name="demo-task"):
        self._tie_breaker = tie_breaker
        self._experiment_id = "exp-1"
        self._config = SimpleNamespace(tiebreaker_tolerance=0.01)
        self._db = SimpleNamespace(
            fetchone=lambda *args, **kw: (
                {"artifact_hash": "parent-hash"}
                if "FROM candidate" in args[0]
                else {"task_name": task_name}
            )
        )
        self._artifact_store = SimpleNamespace(
            load_text=lambda h: "parent code" if h == "parent-hash" else "child code"
        )


class TestTieBreakIntegration:
    def _step(self, engine):
        return FastLoopStep(engine)

    def test_tie_breaks_and_adds_bounded_bonus(self):
        llm = FakeLLM(responses=["B", "B", "B"])
        breaker = DiscreteTieBreaker(llm, tolerance=0.01, repetitions=3, bonus_cap=0.01)
        engine = _EngineStub(breaker)
        step = self._step(engine)
        output = EvalOutput(
            score=0.5,
            metrics={"search_score": 0.5},
            passed=True,
        )
        new_score = step._apply_tie_break_bonus(
            output,
            candidate_id="child-1",
            artifact_hash="child-hash",
            parent_ids=["parent-1"],
            parent_best=0.505,  # 打平：|0.5-0.505|=0.005 ≤ 0.01
        )
        assert new_score > 0.5  # bonus 生效
        assert new_score <= 0.5 + 0.01  # 有界
        assert output.metrics["tie_break_preferred_child"] == 1.0
        assert output.metrics["tie_break_bonus"] > 0

    def test_no_tie_skips_comparison(self):
        llm = FakeLLM(responses=["B"])
        breaker = DiscreteTieBreaker(llm, tolerance=0.01, repetitions=3, bonus_cap=0.01)
        engine = _EngineStub(breaker)
        step = self._step(engine)
        output = EvalOutput(score=0.8, metrics={"search_score": 0.8}, passed=True)
        new_score = step._apply_tie_break_bonus(
            output,
            candidate_id="child-1",
            artifact_hash="child-hash",
            parent_ids=["parent-1"],
            parent_best=0.5,  # 不打平
        )
        assert new_score == 0.8
        assert "tie_break_bonus" not in output.metrics

    def test_disabled_engine_skips(self):
        engine = _EngineStub(None)
        step = self._step(engine)
        output = EvalOutput(score=0.5, metrics={"search_score": 0.5}, passed=True)
        new_score = step._apply_tie_break_bonus(
            output,
            candidate_id="child-1",
            artifact_hash="child-hash",
            parent_ids=["parent-1"],
            parent_best=0.505,
        )
        assert new_score == 0.5

    def test_failed_candidate_never_tie_breaks(self):
        llm = FakeLLM(responses=["B"])
        breaker = DiscreteTieBreaker(llm, tolerance=0.01, repetitions=3, bonus_cap=0.01)
        engine = _EngineStub(breaker)
        step = self._step(engine)
        output = EvalOutput(score=0.0, metrics={"search_score": 0.0}, passed=False)
        new_score = step._apply_tie_break_bonus(
            output,
            candidate_id="child-1",
            artifact_hash="child-hash",
            parent_ids=["parent-1"],
            parent_best=0.0,
        )
        assert new_score == 0.0
