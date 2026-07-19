"""Coder Agent - 代码生成.

S5-07: 实现 CoderAgent diff/full rewrite
"""

from __future__ import annotations

import json
import logging

from omnievolve.agents.base import AgentContext, CodeOutput, ThoughtOutput
from omnievolve.agents.llm_gateway import LLMGateway

logger = logging.getLogger(__name__)

CODER_SYSTEM_PROMPT = """You are the Coder Agent in an evolutionary code optimization system.
Your role is to implement the improvement thought as code changes.

Given the parent code and the improvement thought, generate the modified code.

Output format (JSON):
{
    "full_code": "The complete modified code",
    "diff": "Summary of changes made",
    "explanation": "How the changes implement the thought",
    "touched_files": ["file1.py", "file2.py"]
}
"""


class Coder:
    """Coder Agent - 负责代码生成."""

    def __init__(
        self,
        llm: LLMGateway,
        *,
        model: str | None = None,
        system_prompt: str | None = None,
    ) -> None:
        self._llm = llm
        self._model = model
        self._system_prompt = system_prompt or CODER_SYSTEM_PROMPT

    def generate_code(self, ctx: AgentContext, thought: ThoughtOutput) -> CodeOutput:
        """生成代码.

        基于思想生成代码修改。
        """
        user_message = self._build_user_message(ctx, thought)

        messages = [
            {"role": "system", "content": ctx.system_prompt or self._system_prompt},
            {"role": "user", "content": user_message},
        ]

        response = self._llm.chat(
            messages,
            model=ctx.model or self._model,
            temperature=0.3,  # 较低温度保证代码质量
            experiment_id=ctx.experiment_id,
            agent_role="coder",
            prompt_version_id=ctx.prompt_version_id or None,
        )

        return self._parse_response(response.content)

    def _build_user_message(self, ctx: AgentContext, thought: ThoughtOutput) -> str:
        """构建用户消息."""
        parts = [
            f"## Improvement Thought:\n{thought.thought}",
            f"\n## Rationale:\n{thought.rationale}",
        ]

        if ctx.parent_artifact_hashes:
            parts.append("\n## Parent Code Hashes:")
            for h in ctx.parent_artifact_hashes[:2]:
                parts.append(f"- {h}")

        parts.append("\n## Instructions:")
        parts.append("Generate the complete modified code that implements this thought.")

        return "\n".join(parts)

    def _parse_response(self, content: str) -> CodeOutput:
        """解析 LLM 响应."""
        try:
            data = json.loads(content)
            return CodeOutput(
                diff=data.get("diff", ""),
                full_code=data.get("full_code", content),
                explanation=data.get("explanation", ""),
                touched_files=data.get("touched_files", []),
            )
        except json.JSONDecodeError:
            # 回退：假设整个内容是代码
            return CodeOutput(
                diff="",
                full_code=content,
                explanation="",
            )
