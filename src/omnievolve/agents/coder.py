"""Coder Agent — 代码生成（AlphaEvolve SEARCH/REPLACE diff 格式）.

S5-07: CoderAgent diff/full rewrite
AM-01: SEARCH/REPLACE diff 格式 + EVOLVE-BLOCK 感知
2.3: 多模式生成 (TARGETED_DIFF / FULL_REWRITE / FUSION_AWARE)
"""

from __future__ import annotations

import json
import logging
from enum import Enum

from omnievolve.agents.base import AgentContext, CodeOutput, ThoughtOutput
from omnievolve.agents.llm_gateway import LLMGateway

logger = logging.getLogger(__name__)


class GenerationMode(str, Enum):
    """2.3: 代码生成模式."""

    TARGETED_DIFF = "targeted_diff"  # 默认：SEARCH/REPLACE 微调
    FULL_REWRITE = "full_rewrite"  # 停滞时：全量重写
    FUSION_AWARE = "fusion_aware"  # 融合时：参考多方案整合
    STEPWISE = "stepwise"  # Phase 9: 分步生成（data→model→training）


CODER_SYSTEM_PROMPT = """You are the Coder Agent in an evolutionary code optimization system.
Your role is to improve code by proposing targeted edits using SEARCH/REPLACE blocks.

Given the current code and an improvement thought, propose one or more SEARCH/REPLACE edits.

Output format — use SEARCH/REPLACE blocks:

<<<<<<< SEARCH
# Exact code to find and replace
=======
# New code that replaces the original code
>>>>>>> REPLACE

Rules:
- SEARCH must match EXACTLY (whitespace, indentation, everything).
- Make minimal, focused changes — do not rewrite the entire code.
- Each REPLACE block should be a meaningful improvement.
- You may propose multiple SEARCH/REPLACE blocks for multiple changes."""


CODER_FALLBACK_PROMPT = """You are the Coder Agent in an evolutionary code optimization system.
Your role is to implement the improvement thought as code changes.

Output format (JSON):
{
    "full_code": "The complete modified code",
    "diff": "Summary of changes made",
    "explanation": "How the changes implement the thought"
}
"""


class Coder:
    """Coder Agent — 生成 SEARCH/REPLACE diff 或全量代码."""

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
        """生成代码 — 2.3: 根据停滞等级自动选择生成模式."""
        mode = self._select_mode(ctx)
        user_message = self._build_user_message(ctx, thought)

        # 模式影响 system prompt 和 temperature
        if mode == GenerationMode.FULL_REWRITE:
            system_prompt = CODER_FALLBACK_PROMPT
            temperature = 0.6  # 更高温度鼓励创新
            user_message += (
                "\n\n## MODE: FULL REWRITE\n"
                "The current approach has stagnated. Propose a fundamentally different "
                "implementation. Output the complete code as JSON with 'full_code' key."
            )
        elif mode == GenerationMode.FUSION_AWARE:
            system_prompt = ctx.system_prompt or self._system_prompt
            temperature = 0.4
            user_message += (
                "\n\n## MODE: FUSION AWARE\n"
                "Analyze the reference solutions above. Selectively incorporate "
                "their best elements while preserving the current code's strengths."
            )
        else:
            system_prompt = ctx.system_prompt or self._system_prompt
            temperature = 0.3

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]

        response = self._llm.chat(
            messages,
            model=ctx.model or self._model,
            temperature=temperature,
            experiment_id=ctx.experiment_id,
            agent_role="coder",
            prompt_version_id=ctx.prompt_version_id or None,
        )

        return self._parse_response(response.content, ctx)

    @staticmethod
    def _select_mode(ctx: AgentContext) -> GenerationMode:
        """2.3: 根据上下文状态选择生成模式."""
        if ctx.stagnation_level >= 3:
            return GenerationMode.STEPWISE  # Phase 9: 极度停滞时分步生成
        if ctx.stagnation_level >= 2:
            return GenerationMode.FULL_REWRITE
        # 如果有多个高分参考程序（融合场景）
        high_score_refs = [p for p in ctx.inspiration_programs if p.get("score", 0) > 0]
        if len(high_score_refs) >= 2 and ctx.stagnation_level >= 1:
            return GenerationMode.FUSION_AWARE
        return GenerationMode.TARGETED_DIFF

    def _build_user_message(self, ctx: AgentContext, thought: ThoughtOutput) -> str:
        """构建用户消息 — 含父代码 + 高分历史程序 + 上次失败反馈."""
        parts = [
            f"## Improvement Thought:\n{thought.thought}",
            f"\n## Rationale:\n{thought.rationale}",
        ]

        # 父代码（用于 diff 基础）
        parent_code = self._get_parent_code(ctx)
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
        parts.append(instruction)

        return "\n".join(parts)

    def _parse_response(self, content: str, ctx: AgentContext) -> CodeOutput:
        """解析 LLM 响应 — 优先 SEARCH/REPLACE diff，回退 JSON/全量."""
        from omnievolve.engine.diff import apply_diffs_with_retry, parse_diffs

        # 尝试 1: SEARCH/REPLACE diff
        diffs = parse_diffs(content)
        if diffs:
            parent_code = self._get_parent_code(ctx)
            if parent_code:
                result, applied, error = apply_diffs_with_retry(parent_code, diffs)
                if result is not None and applied == len(diffs):
                    return CodeOutput(
                        diff=content[:500],
                        full_code=result,
                        explanation=f"Applied {applied} SEARCH/REPLACE block(s)",
                        touched_files=[],
                    )
                if error:
                    logger.debug(
                        "Rejected non-atomic SEARCH/REPLACE response (%d/%d applied): %s",
                        applied,
                        len(diffs),
                        error,
                    )
            return CodeOutput(
                diff=content[:500],
                full_code="",
                explanation=(
                    f"Parsed {len(diffs)} diff block(s) but could not apply all blocks atomically"
                ),
            )

        # 尝试 2: JSON 格式（回退）
        try:
            data = json.loads(content)
            return CodeOutput(
                diff=data.get("diff", ""),
                full_code=data.get("full_code", content),
                explanation=data.get("explanation", ""),
                touched_files=data.get("touched_files", []),
            )
        except json.JSONDecodeError:
            pass

        # 尝试 3: 提取 ```python ... ``` 代码块
        import re

        code_blocks = re.findall(r"```(?:python)?\s*\n(.*?)```", content, re.DOTALL)
        if code_blocks:
            return CodeOutput(
                diff="",
                full_code=code_blocks[-1].strip(),
                explanation="Extracted from code block",
            )

        # 回退: 整个响应作为代码
        return CodeOutput(
            diff="",
            full_code=content,
            explanation="Raw content used as code",
        )

    def _get_parent_code(self, ctx: AgentContext) -> str:
        """从上下文获取父代码."""
        if ctx.inspiration_programs:
            for prog in ctx.inspiration_programs:
                if prog.get("is_parent") and prog.get("code"):
                    return prog["code"]
        return ""
