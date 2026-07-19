"""Context Builder.

S5-05: 实现 ContextBuilder 与 token budget
"""

from __future__ import annotations

import logging
from typing import Any

from omnievolve.agents.base import AgentContext
from omnievolve.utils.token_counter import estimate_tokens

logger = logging.getLogger(__name__)

# 各角色的 token 预算比例
ROLE_BUDGET_RATIO = {
    "director": 0.25,
    "coder": 0.40,
    "critic": 0.15,
    "meta": 0.20,
}

# 上下文各部分的优先级（从高到低）
CONTEXT_PRIORITIES = [
    "task_description",
    "parent_code",
    "improvement_thought",
    "memory_hits",
    "domain_hints",
    "parent_thoughts",
    "evaluation_history",
    "search_policy",
]


class ContextBuilder:
    """Agent 上下文构建器.

    负责将多种来源的信息组装成 LLM 上下文，
    并在 token 预算内进行裁剪。
    """

    def __init__(
        self,
        total_token_budget: int = 100_000,
        *,
        reserve_output: int = 4_000,
    ) -> None:
        """初始化.

        Args:
            total_token_budget: 总 token 预算
            reserve_output: 为输出预留的 token
        """
        self._total_budget = total_token_budget
        self._input_budget = total_token_budget - reserve_output

    def build_director_context(
        self,
        base_ctx: AgentContext,
        *,
        memory_hits: list[dict] | None = None,
        parent_thoughts: list[str] | None = None,
        domain_hints: list[str] | None = None,
    ) -> str:
        """构建 Director 上下文."""
        budget = int(self._input_budget * ROLE_BUDGET_RATIO["director"])
        parts = []

        # 任务描述（高优先级）
        parts.append(f"# Task: {base_ctx.task_id}")
        parts.append(f"# Generation: {base_ctx.generation}")

        # 父代思想
        if parent_thoughts:
            parts.append("\n## Parent Thoughts:")
            used_tokens = sum(estimate_tokens(p) for p in parts)
            for thought in parent_thoughts[:3]:
                thought_tokens = estimate_tokens(thought)
                if used_tokens + thought_tokens > budget * 0.4:
                    break
                parts.append(f"- {thought[:500]}")
                used_tokens += thought_tokens

        # 记忆命中
        if memory_hits:
            parts.append("\n## Relevant Memories:")
            used_tokens = sum(estimate_tokens(p) for p in parts)
            for mem in memory_hits[:5]:
                mem_text = mem.get("outcome_summary", "")
                mem_tokens = estimate_tokens(mem_text)
                if used_tokens + mem_tokens > budget * 0.7:
                    break
                parts.append(f"- {mem_text[:300]}")
                used_tokens += mem_tokens

        # 领域提示
        if domain_hints:
            parts.append("\n## Domain Hints:")
            for hint in domain_hints[:3]:
                parts.append(f"- {hint}")

        parts.append("\nPropose an innovative improvement thought.")

        context = "\n".join(parts)
        return self._truncate(context, budget)

    def build_coder_context(
        self,
        base_ctx: AgentContext,
        thought: str,
        parent_code: str | None = None,
    ) -> str:
        """构建 Coder 上下文."""
        budget = int(self._input_budget * ROLE_BUDGET_RATIO["coder"])
        parts = []

        # 思想（高优先级）
        parts.append(f"# Improvement Thought:\n{thought}")

        # 父代代码
        if parent_code:
            parts.append(f"\n## Parent Code:\n```python\n{parent_code}\n```")

        parts.append("\n## Instructions:")
        parts.append("Generate the complete modified code that implements this thought.")

        context = "\n".join(parts)
        return self._truncate(context, budget)

    def build_critic_context(
        self,
        code: str,
        thought: str,
    ) -> str:
        """构建 Critic 上下文."""
        budget = int(self._input_budget * ROLE_BUDGET_RATIO["critic"])
        parts = [
            f"# Thought:\n{thought}",
            f"\n# Code:\n```python\n{code}\n```",
            "\nReview this code for correctness and alignment with the thought.",
        ]
        context = "\n".join(parts)
        return self._truncate(context, budget)

    def _truncate(self, text: str, budget: int) -> str:
        """在 token 预算内截断文本."""
        tokens = estimate_tokens(text)
        if tokens <= budget:
            return text

        # 粗略计算截断位置
        char_limit = budget * 4  # 4 字符约 1 token
        if len(text) > char_limit:
            return text[:char_limit] + "\n... [truncated]"
        return text


class AgentRetryHandler:
    """Agent retry / backoff / fallback.

    S5-10: 实现 Agent retry/backoff/fallback
    """

    def __init__(
        self,
        max_retries: int = 3,
        *,
        initial_delay: float = 1.0,
        max_delay: float = 30.0,
        backoff_factor: float = 2.0,
    ) -> None:
        self._max_retries = max_retries
        self._initial_delay = initial_delay
        self._max_delay = max_delay
        self._backoff_factor = backoff_factor

    def execute_with_retry(
        self,
        func: Any,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """带重试执行函数.

        Args:
            func: 要执行的函数
            *args, **kwargs: 函数参数

        Returns:
            函数返回值

        Raises:
            最后一次异常
        """
        import time

        last_error = None
        delay = self._initial_delay

        for attempt in range(self._max_retries + 1):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                last_error = e
                if attempt >= self._max_retries:
                    logger.error(f"Failed after {self._max_retries + 1} attempts: {e}")
                    raise

                logger.warning(f"Attempt {attempt + 1} failed: {e}, retrying in {delay:.1f}s")
                time.sleep(delay)
                delay = min(delay * self._backoff_factor, self._max_delay)

        raise last_error  # type: ignore
