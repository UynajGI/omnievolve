"""Context Builder.

S5-05: 实现 ContextBuilder 与 token budget
"""

from __future__ import annotations

import logging
from typing import Any

from omnievolve.agents.base import AgentContext, ThoughtOutput
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

    # ------------------------------------------------------------------ #
    # 1.2: AgentContext 完整版构建（fast_loop 生产路径）。
    # 从 Director/Coder 的 _build_user_message 保真迁移：标题、顺序、
    # 截断阈值与原先一致，并统一套用角色 token 预算裁剪。
    # ------------------------------------------------------------------ #

    def build_director_user_message(self, ctx: AgentContext) -> str:
        """构建 Director 用户消息（完整版）.

        保留 P2-1 停滞层级、反例集合（meta_scratchpad）、兄弟摘要、
        RAG 检索等既有提示结构；末尾统一按 director 预算截断。
        """
        budget = int(self._input_budget * ROLE_BUDGET_RATIO["director"])
        parts = [
            f"## Task: {ctx.task_id}",
            f"## Generation: {ctx.generation}",
        ]

        # P2-1: 停滞层级指导
        if ctx.stagnation_level > 0:
            tier = min(ctx.stagnation_level + 1, 3)  # level 1→Tier2, level 2+→Tier3
            parts.append(
                f"\n## ⚠️ Stagnation Detected (level={ctx.stagnation_level})\n"
                f"Recent attempts have NOT improved scores. "
                f"You MUST propose a **Tier {tier}** change (see system prompt).\n"
                f"Do NOT repeat minor tweaks — make a "
                f"{'fundamental' if tier >= 3 else 'significant'} change."
            )

        if ctx.parent_thoughts:
            parts.append("\n## Parent Thoughts:")
            for i, thought in enumerate(ctx.parent_thoughts[:3]):
                parts.append(f"{i + 1}. {thought[:500]}")

        if ctx.memory_hits:
            parts.append("\n## Relevant Memories:")
            for mem in ctx.memory_hits[:3]:
                parts.append(f"- {mem.get('outcome_summary', '')[:200]}")

        # 1.2: 兄弟节点摘要（同一 island 最近尝试，避免重复）
        if ctx.sibling_summaries:
            parts.append("\n## Sibling Approaches (same island, recent):")
            for s in ctx.sibling_summaries[:3]:
                parts.append(f"- {s}")

        # 向量 RAG 检索（语义相关的历史 thought）
        if ctx.rag_context:
            parts.append("\n## Semantically Related Thoughts (vector retrieval):")
            for r in ctx.rag_context[:3]:
                parts.append(f"- {r.get('content', '')[:200]}")

        # P2-1: 反例集合（从 meta_scratchpad 取失败方向）
        if ctx.meta_scratchpad:
            parts.append(f"\n## Failed Directions (AVOID repeating):\n{ctx.meta_scratchpad[:500]}")

        if ctx.domain_hints:
            parts.append("\n## Domain Hints:")
            for hint in ctx.domain_hints[:3]:
                parts.append(f"- {hint}")

        parts.append("\nPropose an innovative improvement thought.")

        return self._truncate("\n".join(parts), budget)

    def build_coder_user_message(self, ctx: AgentContext, thought: ThoughtOutput) -> str:
        """构建 Coder 用户消息（完整版）.

        保真保留父代码 → 失败反馈 → inspiration → 兄弟摘要 → 记忆的
        既有顺序与标题（tests/agents/test_eval_feedback.py 依赖该顺序）；
        末尾统一按 coder 预算截断。
        """
        budget = int(self._input_budget * ROLE_BUDGET_RATIO["coder"])
        parts = [
            f"## Improvement Thought:\n{thought.thought}",
            f"\n## Rationale:\n{thought.rationale}",
        ]

        # 父代码（用于 diff 基础）
        parent_code = self._parent_code_from_ctx(ctx)
        if parent_code:
            parts.append(f"\n## Current Code to Improve:\n```python\n{parent_code}\n```")

        # P0-1: 上次评估失败反馈（如果有）
        if ctx.last_eval_failure:
            parts.append(
                f"\n## ⚠ Previous Evaluation Failure (avoid repeating):\n"
                f"```\n{ctx.last_eval_failure}\n```"
            )

        # Inspiration: 高分历史程序
        if ctx.inspiration_programs:
            parts.append("\n## High-Scoring Programs for Inspiration:")
            for prog in ctx.inspiration_programs[:3]:
                score = prog.get("score", "?")
                code = prog.get("code", "")
                if len(code) > 1500:  # P2-2: 截断从 800 提升到 1500
                    code = code[:1500] + "\n... (truncated)"
                parts.append(f"Score: {score}\n```python\n{code}\n```")

        # P2-2: 兄弟节点摘要
        if ctx.sibling_summaries:
            parts.append("\n## Sibling Approaches (same island, recent):")
            for s in ctx.sibling_summaries[:3]:
                parts.append(f"- {s}")

        # 记忆摘要
        if ctx.memory_hits:
            parts.append("\n## Past Insights:")
            for m in ctx.memory_hits[:3]:
                parts.append(f"- {m.get('outcome_summary', '')[:200]}")

        parts.append("\n## Instructions:")
        instruction = (
            "Propose targeted SEARCH/REPLACE edits to improve the current code. "
            "Make minimal, focused changes."
        )
        if ctx.last_eval_failure:
            instruction += (
                " Pay special attention to the previous failure above — "
                "ensure your edits fix the root cause, not just the symptom."
            )
        if ctx.generation_mode == "point":
            instruction += " Make exactly one localized semantic change."
        elif ctx.generation_mode == "repair":
            instruction += (
                " Treat this as a repair operator: preserve working behavior and "
                "focus on the most likely correctness or execution defect."
            )
        elif ctx.generation_mode == "diff":
            instruction += " Prefer a small atomic SEARCH/REPLACE patch."
        parts.append(instruction)

        return self._truncate("\n".join(parts), budget)

    @staticmethod
    def _parent_code_from_ctx(ctx: AgentContext) -> str:
        """从上下文的 inspiration 程序中提取父代码."""
        for prog in ctx.inspiration_programs:
            if prog.get("is_parent") and prog.get("code"):
                return prog["code"]
        return ""

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
