"""Fusion Agent - LLM 语义融合.

设计文档 §7: 多父代跨分支融合
参考 MLEvolve fusion_agent: LLM 理解多分支意图后智能合并

与 CrossoverOperator（机械文本拼接）不同，FusionAgent 让 LLM：
1. 理解 WHY 参考方案成功
2. 分析 HOW 将优势应用到当前方案
3. 决定 WHAT 选择性采纳
"""

from __future__ import annotations

import logging

from omnievolve.agents.base import CodeOutput
from omnievolve.agents.llm_gateway import LLMGateway

logger = logging.getLogger(__name__)

FUSION_SYSTEM_PROMPT = """You are the Fusion Agent in an evolutionary code optimization system.
Your role is to intelligently merge the best aspects of multiple code solutions.

You will receive:
1. A SOURCE solution (the current branch's best code)
2. One or more REFERENCE solutions (high-scoring code from other branches)
3. Performance data for each solution

Your task:
- Analyze WHY each reference solution performs well
- Identify specific techniques, algorithms, or patterns that contribute to its success
- Selectively incorporate the best elements into the source solution
- Preserve the source solution's strengths while adding reference advantages
- Output the complete merged code

Rules:
- Do NOT simply concatenate code — understand and integrate semantically
- Resolve conflicts intelligently (prefer the higher-scoring approach)
- Maintain code coherence and avoid duplication
- The output must be a complete, runnable program"""


class FusionAgent:
    """LLM 语义融合 Agent.

    当停滞等级 >= 2 且存在跨 island 高分候选时调用，
    替代机械 crossover 实现真正的 1+1>2 融合。
    """

    def __init__(
        self,
        llm: LLMGateway,
        *,
        model: str | None = None,
        max_reference_code_chars: int = 3000,
    ) -> None:
        self._llm = llm
        self._model = model
        self._max_ref_chars = max_reference_code_chars

    def fuse(
        self,
        source_code: str,
        references: list[dict],
        *,
        experiment_id: str | None = None,
    ) -> CodeOutput:
        """执行语义融合.

        Args:
            source_code: 当前分支的源代码
            references: 参考方案列表 [{"code": str, "score": float, "thought": str}, ...]
            experiment_id: 实验 ID

        Returns:
            CodeOutput 融合后的完整代码
        """
        user_message = self._build_fusion_prompt(source_code, references)

        messages = [
            {"role": "system", "content": FUSION_SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ]

        response = self._llm.chat(
            messages,
            model=self._model,
            temperature=0.4,  # 中等温度：创造性但不过度发散
            experiment_id=experiment_id,
            agent_role="coder",
        )

        # 提取代码
        full_code = self._extract_code(response.content)
        return CodeOutput(
            diff="",
            full_code=full_code,
            explanation=f"LLM semantic fusion of {len(references)} reference(s)",
        )

    def _build_fusion_prompt(self, source_code: str, references: list[dict]) -> str:
        """构建融合 prompt."""
        parts = ["## SOURCE Solution (current branch):"]
        parts.append(f"```python\n{source_code[:5000]}\n```")

        parts.append("\n## REFERENCE Solutions (from other branches):")
        for i, ref in enumerate(references[:3], 1):
            code = ref.get("code", "")[:self._max_ref_chars]
            score = ref.get("score", "?")
            thought = ref.get("thought", "")[:300]
            parts.append(f"\n### Reference #{i} (score={score}):")
            if thought:
                parts.append(f"Strategy: {thought}")
            parts.append(f"```python\n{code}\n```")

        parts.append("\n## Instructions:")
        parts.append(
            "Analyze the reference solutions, identify their key advantages, "
            "and produce a merged solution that combines the best elements. "
            "Output the COMPLETE merged code in a single ```python block."
        )

        return "\n".join(parts)

    @staticmethod
    def _extract_code(content: str) -> str:
        """从 LLM 响应中提取代码."""
        import re

        # 尝试提取 ```python ... ``` 代码块
        code_blocks = re.findall(r"```(?:python)?\s*\n(.*?)```", content, re.DOTALL)
        if code_blocks:
            return code_blocks[-1].strip()
        # 回退：整个响应作为代码
        return content.strip()
