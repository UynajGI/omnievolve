"""Director Agent - 思想进化.

S5-06: 实现 DirectorAgent 最小版本
P2-1: 分层改进策略 + 停滞检测升级
"""

from __future__ import annotations

import json
import logging
from typing import Any

from omnievolve.agents.base import AgentContext, ThoughtOutput
from omnievolve.agents.llm_gateway import LLMGateway

logger = logging.getLogger(__name__)

DIRECTOR_SYSTEM_PROMPT = """You are the Director Agent in an evolutionary code optimization system.
Your role is to propose innovative ideas for improving the candidate code.

Analyze the parent code, past experiences, and domain hints to generate a creative improvement thought.

## Improvement Strategy Tiers (P2-1)

Classify your thought into one of these tiers based on the stagnation level:

**Tier 1: Optimization (The "How")**
- Keep the algorithm/architecture fixed. Only change HOW it runs.
- Scope: hyperparameters, constants, loop bounds, data structures, caching.
- Use when: stagnation_level = 0 or 1.

**Tier 2: Representation & Components (The "What")**
- Change specific modules/algorithms, but keep the overall paradigm.
- Scope: different algorithm, new data structure, alternative approach for a sub-problem.
- Use when: stagnation_level = 2.

**Tier 3: Paradigm Shift (The "Why")**
- Fundamentally rethink the approach. Change the underlying paradigm.
- Scope: completely different algorithm family, mathematical reformulation.
- Use when: stagnation_level >= 3.

Output format (JSON):
{
    "thought": "Your main improvement idea",
    "rationale": "Why this should work",
    "risk_notes": "Potential risks or downsides",
    "confidence": 0.0-1.0,
    "mechanism_tags": ["tag1", "tag2"],
    "tier": 1-3
}
"""


class Director:
    """Director Agent - 负责思想进化."""

    def __init__(
        self,
        llm: LLMGateway,
        *,
        model: str | None = None,
        system_prompt: str | None = None,
        context_builder: Any | None = None,
    ) -> None:
        self._llm = llm
        self._model = model
        self._system_prompt = system_prompt or DIRECTOR_SYSTEM_PROMPT
        # 1.2: 上下文统一由 ContextBuilder 构建（预算裁剪单一入口）。
        from omnievolve.agents.context_builder import ContextBuilder

        self._context_builder = context_builder or ContextBuilder()

    def evolve_thought(self, ctx: AgentContext) -> ThoughtOutput:
        """进化思想.

        基于父代、记忆和领域提示生成改进思想。
        """
        # 构建用户消息
        user_message = self._build_user_message(ctx)

        messages = [
            {"role": "system", "content": ctx.system_prompt or self._system_prompt},
            {"role": "user", "content": user_message},
        ]

        response = self._llm.chat(
            messages,
            model=ctx.model or self._model,
            temperature=0.8,  # 较高温度鼓励创新
            experiment_id=ctx.experiment_id,
            agent_role="director",
            prompt_version_id=ctx.prompt_version_id or None,
        )

        # 解析响应
        return self._parse_response(response.content)

    def _build_user_message(self, ctx: AgentContext) -> str:
        """构建用户消息 — 1.2: 统一委托 ContextBuilder（预算裁剪单一入口）."""
        return self._context_builder.build_director_user_message(ctx)

    def _parse_response(self, content: str) -> ThoughtOutput:
        """解析 LLM 响应."""
        try:
            # 尝试解析 JSON
            data = json.loads(content)
            return ThoughtOutput(
                thought=data.get("thought", content),
                rationale=data.get("rationale", ""),
                risk_notes=data.get("risk_notes", ""),
                confidence=float(data.get("confidence", 0.5)),
                mechanism_tags=data.get("mechanism_tags", []),
            )
        except json.JSONDecodeError:
            # 回退：使用原始内容
            return ThoughtOutput(
                thought=content,
                rationale="",
                confidence=0.5,
            )
