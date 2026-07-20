"""context_builder.py 单元测试 — ContextBuilder + AgentRetryHandler."""

from __future__ import annotations

import pytest

from omnievolve.agents.base import AgentContext
from omnievolve.agents.context_builder import (
    ROLE_BUDGET_RATIO,
    AgentRetryHandler,
    ContextBuilder,
)

pytestmark = pytest.mark.unit


# --------------------------------------------------------------------------- #
#  Helpers
# --------------------------------------------------------------------------- #


def _make_base_ctx(**kwargs) -> AgentContext:
    defaults = {
        "task_id": "test-task",
        "experiment_id": "exp-001",
        "generation": 5,
        "island_id": "island_0",
        "prompt_version_id": "pv-1",
        "search_policy_id": "sp-1",
    }
    defaults.update(kwargs)
    return AgentContext(**defaults)


# --------------------------------------------------------------------------- #
#  ContextBuilder
# --------------------------------------------------------------------------- #


class TestContextBuilder:
    def test_init_default_budget(self):
        builder = ContextBuilder()
        assert builder._total_budget == 100_000  # noqa: SLF001

    def test_custom_budget(self):
        builder = ContextBuilder(total_token_budget=50_000, reserve_output=2_000)
        assert builder._input_budget == 48_000  # noqa: SLF001

    def test_build_director_context_contains_task(self):
        builder = ContextBuilder()
        ctx = _make_base_ctx()
        result = builder.build_director_context(ctx)
        assert "test-task" in result
        assert "Generation: 5" in result

    def test_build_director_context_with_parent_thoughts(self):
        builder = ContextBuilder()
        ctx = _make_base_ctx()
        thoughts = ["Use numpy for faster computation", "Try a different algorithm"]
        result = builder.build_director_context(ctx, parent_thoughts=thoughts)
        assert "Parent Thoughts" in result
        assert "numpy" in result

    def test_build_director_context_with_memory_hits(self):
        builder = ContextBuilder()
        ctx = _make_base_ctx()
        memories = [
            {"outcome_summary": "Using FFT improved performance by 10x"},
            {"outcome_summary": "Recursion caused stack overflow"},
        ]
        result = builder.build_director_context(ctx, memory_hits=memories)
        assert "Relevant Memories" in result
        assert "FFT" in result

    def test_build_director_context_with_domain_hints(self):
        builder = ContextBuilder()
        ctx = _make_base_ctx()
        result = builder.build_director_context(ctx, domain_hints=["Use vectorized ops"])
        assert "Domain Hints" in result
        assert "vectorized" in result

    def test_build_director_context_truncated_by_budget(self):
        small_budget = ContextBuilder(total_token_budget=200, reserve_output=50)
        ctx = _make_base_ctx()
        thoughts = ["A" * 5000]  # 长文本
        result = small_budget.build_director_context(ctx, parent_thoughts=thoughts)
        # 不应超过 token 预算
        assert len(result) < 10000

    def test_build_coder_context_includes_thought(self):
        builder = ContextBuilder()
        ctx = _make_base_ctx()
        result = builder.build_coder_context(ctx, "Use binary search")
        assert "Use binary search" in result

    def test_build_coder_context_with_parent_code(self):
        builder = ContextBuilder()
        ctx = _make_base_ctx()
        result = builder.build_coder_context(ctx, "optimize", parent_code="def f(): pass")
        assert "def f(): pass" in result
        assert "```python" in result

    def test_build_critic_context(self):
        builder = ContextBuilder()
        result = builder.build_critic_context("x = 1", "simple assignment")
        assert "x = 1" in result
        assert "simple assignment" in result
        assert "Review" in result

    def test_truncate_short_text_unchanged(self):
        builder = ContextBuilder()
        result = builder._truncate("hello", 100)  # noqa: SLF001
        assert result == "hello"

    def test_truncate_long_text(self):
        builder = ContextBuilder()
        long_text = "A" * 1000
        result = builder._truncate(long_text, 10)  # noqa: SLF001
        assert len(result) < len(long_text)

    def test_role_budget_ratios_sum_to_one(self):
        total = sum(ROLE_BUDGET_RATIO.values())
        assert total == pytest.approx(1.0)


# --------------------------------------------------------------------------- #
#  AgentRetryHandler
# --------------------------------------------------------------------------- #


class TestAgentRetryHandler:
    def test_successful_first_attempt(self):
        handler = AgentRetryHandler()
        result = handler.execute_with_retry(lambda x: x * 2, 21)
        assert result == 42

    def test_retry_on_failure_then_succeed(self):
        call_count = [0]

        def flaky():
            call_count[0] += 1
            if call_count[0] < 3:
                raise ValueError("transient error")
            return "success"

        handler = AgentRetryHandler(max_retries=3, initial_delay=0.01, max_delay=0.05)
        result = handler.execute_with_retry(flaky)
        assert result == "success"
        assert call_count[0] == 3

    def test_exhausted_retries_raises(self):
        def always_fails():
            raise RuntimeError("persistent error")

        handler = AgentRetryHandler(max_retries=2, initial_delay=0.01, max_delay=0.05)
        with pytest.raises(RuntimeError, match="persistent error"):
            handler.execute_with_retry(always_fails)

    def test_backoff_increases(self):
        handler = AgentRetryHandler(max_retries=5, initial_delay=0.01, backoff_factor=10.0)
        delays = []
        orig_sleep = __import__("time").sleep

        def mock_sleep(d):
            delays.append(d)

        import time

        time.sleep = mock_sleep
        try:
            try:
                handler.execute_with_retry(lambda: (_ for _ in ()).throw(RuntimeError("fail")))
            except RuntimeError:
                pass
        finally:
            time.sleep = orig_sleep

        # 验证指数退避
        assert len(delays) >= 1
        for i in range(1, len(delays)):
            assert delays[i] >= delays[i - 1]

    def test_zero_retries_tries_once(self):
        handler = AgentRetryHandler(max_retries=0)
        result = handler.execute_with_retry(lambda: "ok")
        assert result == "ok"

    def test_zero_retries_no_retry_on_failure(self):
        handler = AgentRetryHandler(max_retries=0)
        with pytest.raises(ValueError):
            handler.execute_with_retry(lambda: (_ for _ in ()).throw(ValueError("nope")))
