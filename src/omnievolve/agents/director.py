"""Director Agent - 思想进化.

S5-06: 实现 DirectorAgent 最小版本
P2-1: 分层改进策略 + 停滞检测升级
"""

from __future__ import annotations

import json
import logging

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
    ) -> None:
        self._llm = llm
        self._model = model
        self._system_prompt = system_prompt or DIRECTOR_SYSTEM_PROMPT

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
        """构建用户消息 — P2-1: 含停滞层级 + 反例集合."""
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
                f"Do NOT repeat minor tweaks — make a {'fundamental' if tier >= 3 else 'significant'} change."
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

        # Step 4: 向量 RAG 检索（语义相关的历史 thought）
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

        return "\n".join(parts)

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
