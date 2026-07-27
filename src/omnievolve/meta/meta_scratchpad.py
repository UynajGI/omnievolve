"""3步 Meta-scratchpad — LLM 驱动的元推理.

从 ShinkaEvolve prompts_meta.py 移植。
Step 1: 个体摘要 → Step 2: 全局洞察 → Step 3: 可操作建议。
集成到 Slow Loop 的健康检查周期。
"""

from __future__ import annotations

import logging
from typing import Any

from omnievolve.agents.prompts.meta import (
    META_STEP1_SYSTEM_MSG,
    META_STEP1_USER_MSG,
    META_STEP2_SYSTEM_MSG,
    META_STEP2_USER_MSG,
    META_STEP3_SYSTEM_MSG,
    META_STEP3_USER_MSG,
)

logger = logging.getLogger(__name__)


class MetaScratchpad:
    """3步元推理引擎.

    Step 1: 为每个候选生成个体摘要
    Step 2: 聚合为全局洞察 scratchpad
    Step 3: 生成可操作建议

    所有步骤使用 LLMGateway，失败时优雅降级。
    """

    def __init__(self, llm: Any) -> None:
        self._llm = llm

    def summarize_individuals(
        self,
        candidates: list[dict],
        max_items: int = 5,
    ) -> list[str]:
        """Step 1: 为候选列表生成个体摘要.

        Args:
            candidates: [{"id", "score", "thought", "code_preview"}]
            max_items: 最多处理多少个候选

        Returns:
            摘要列表
        """
        summaries: list[str] = []
        for cand in candidates[:max_items]:
            try:
                program_msg = (
                    f"Name: {cand.get('thought', '')[:100]}\n"
                    f"Score: {cand.get('score', 'N/A')}\n"
                    f"Code preview: {cand.get('code_preview', '')[:500]}"
                )
                user_msg = META_STEP1_USER_MSG.format(individual_program_msg=program_msg)
                response = self._llm.chat(
                    messages=[
                        {"role": "system", "content": META_STEP1_SYSTEM_MSG},
                        {"role": "user", "content": user_msg},
                    ],
                    model="light",
                    role="meta",
                    temperature=0.3,
                )
                summaries.append(response.content.strip())
            except Exception:
                logger.debug("Meta step 1 failed for candidate", exc_info=True)
                summaries.append(f"[Summary failed: {cand.get('id', '?')}]")

        return summaries

    def extract_insights(
        self,
        individual_summaries: list[str],
        previous_insights: str = "",
        best_program_info: str = "",
    ) -> str:
        """Step 2: 聚合为全局洞察.

        Returns:
            全局洞察文本（含 4 个 section）
        """
        try:
            user_msg = META_STEP2_USER_MSG.format(
                individual_summaries="\n\n".join(individual_summaries),
                previous_insights=previous_insights or "(none)",
                best_program_info=best_program_info or "(unknown)",
            )
            response = self._llm.chat(
                messages=[
                    {"role": "system", "content": META_STEP2_SYSTEM_MSG},
                    {"role": "user", "content": user_msg},
                ],
                model="heavy",
                role="meta",
                temperature=0.4,
            )
            return response.content.strip()
        except Exception:
            logger.debug("Meta step 2 failed", exc_info=True)
            return previous_insights

    def generate_recommendations(
        self,
        insights: str,
        previous_recommendations: str = "",
        best_program_info: str = "",
    ) -> str:
        """Step 3: 生成可操作建议.

        Returns:
            建议文本（bullet list）
        """
        try:
            user_msg = META_STEP3_USER_MSG.format(
                insights=insights,
                previous_recommendations=previous_recommendations or "(none)",
                best_program_info=best_program_info or "(unknown)",
            )
            response = self._llm.chat(
                messages=[
                    {"role": "system", "content": META_STEP3_SYSTEM_MSG},
                    {"role": "user", "content": user_msg},
                ],
                model="heavy",
                role="meta",
                temperature=0.5,
            )
            return response.content.strip()
        except Exception:
            logger.debug("Meta step 3 failed", exc_info=True)
            return previous_recommendations

    def run(
        self,
        candidates: list[dict],
        previous_insights: str = "",
        previous_recommendations: str = "",
        best_program_info: str = "",
    ) -> tuple[str, str]:
        """执行完整 3 步流程.

        Returns:
            (insights, recommendations)
        """
        # Step 1
        summaries = self.summarize_individuals(candidates)

        # Step 2
        insights = self.extract_insights(summaries, previous_insights, best_program_info)

        # Step 3
        recommendations = self.generate_recommendations(
            insights, previous_recommendations, best_program_info
        )

        return insights, recommendations
