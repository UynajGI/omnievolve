"""P0-1: 评估失败反馈闭环测试.

验证 Coder 能看到父代的评估失败信息（stderr/failure_reason），
并在 Prompt 中正确展示，让 LLM 知道上次为什么失败。
"""

from __future__ import annotations

import pytest

from omnievolve.agents.base import AgentContext, ThoughtOutput
from omnievolve.agents.coder import Coder
from omnievolve.agents.llm_gateway import FakeLLM
from omnievolve.engine.fast_loop import _combine_failures

pytestmark = pytest.mark.unit


@pytest.fixture
def fake_llm_with_code():
    """FakeLLM 返回一段可解析为代码块的响应."""
    return FakeLLM(
        responses=[
            "```python\ndef solve():\n    return 42\n```",
        ]
    )


@pytest.fixture
def base_ctx():
    """无失败信息的基准 AgentContext."""
    return AgentContext(
        experiment_id="exp1",
        task_id="sort",
        generation=2,
        island_id="island_0",
        parent_candidate_ids=["parent_1"],
    )


@pytest.fixture
def ctx_with_failure():
    """带失败信息的 AgentContext（模拟父代 pytest 失败）."""
    return AgentContext(
        experiment_id="exp1",
        task_id="sort",
        generation=2,
        island_id="island_0",
        parent_candidate_ids=["parent_1"],
        last_eval_failure="NameError: name 'quicksort' is not defined\nstderr:\nE   NameError: name 'quicksort' is not defined\n=========================== short test summary info ============\nFAILED test_sort.py::test_basic_sort - NameError",
    )


@pytest.fixture
def thought():
    return ThoughtOutput(
        thought="Implement quicksort with proper function definition",
        rationale="Previous attempt referenced undefined function",
    )


class TestCombineFailures:
    """_combine_failures 辅助函数测试."""

    def test_empty_list_returns_empty(self):
        assert _combine_failures([]) == ""

    def test_all_empty_returns_empty(self):
        assert _combine_failures(["", "", ""]) == ""

    def test_returns_first_non_empty(self):
        failures = ["", "NameError: foo", "ValueError: bar"]
        result = _combine_failures(failures)
        assert "NameError: foo" in result
        assert "ValueError" not in result

    def test_truncates_long_failure(self):
        long_failure = "x" * 2000
        result = _combine_failures([long_failure])
        assert len(result) <= 1000

    def test_strips_whitespace(self):
        result = _combine_failures(["  \n  error here  \n  "])
        assert result == "error here"


class TestCoderPromptWithFailure:
    """Coder 在有/无失败信息时的 Prompt 构建测试."""

    def test_coder_without_failure_omits_section(self, fake_llm_with_code, base_ctx, thought):
        """无失败信息时，Prompt 不应包含 Previous Evaluation Failure."""
        coder = Coder(fake_llm_with_code)
        msg = coder._build_user_message(base_ctx, thought)

        assert "Previous Evaluation Failure" not in msg
        assert "avoid repeating" not in msg

    def test_coder_with_failure_includes_section(
        self, fake_llm_with_code, ctx_with_failure, thought
    ):
        """有失败信息时，Prompt 应包含 Previous Evaluation Failure 区块."""
        coder = Coder(fake_llm_with_code)
        msg = coder._build_user_message(ctx_with_failure, thought)

        assert "Previous Evaluation Failure" in msg
        assert "NameError" in msg
        assert "quicksort" in msg
        assert "avoid repeating" in msg

    def test_coder_with_failure_adds_fix_instruction(
        self, fake_llm_with_code, ctx_with_failure, thought
    ):
        """有失败信息时，Instructions 应包含 'fix the root cause' 提示."""
        coder = Coder(fake_llm_with_code)
        msg = coder._build_user_message(ctx_with_failure, thought)

        assert "root cause" in msg

    def test_coder_without_failure_no_fix_instruction(self, fake_llm_with_code, base_ctx, thought):
        """无失败信息时，Instructions 不应包含 fix root cause 提示."""
        coder = Coder(fake_llm_with_code)
        msg = coder._build_user_message(base_ctx, thought)

        assert "root cause" not in msg

    def test_failure_section_appears_after_parent_code(
        self, fake_llm_with_code, ctx_with_failure, thought
    ):
        """失败信息应出现在父代码之后、inspiration 之前."""
        # 添加父代码到 inspiration
        ctx_with_failure.__dict__["inspiration_programs"] = [  # type: ignore[misc]
            {"is_parent": True, "code": "def old(): pass", "score": 0.5}
        ]
        coder = Coder(fake_llm_with_code)
        msg = coder._build_user_message(ctx_with_failure, thought)

        parent_pos = msg.find("Current Code to Improve")
        failure_pos = msg.find("Previous Evaluation Failure")
        inspiration_pos = msg.find("High-Scoring Programs")

        assert parent_pos < failure_pos, "Failure should come after parent code"
        assert failure_pos < inspiration_pos, "Failure should come before inspiration"
