"""Data Leakage Detector — 数据泄漏检测.

从 MLEvolve data_leakage_agent.py 精简移植。
启发式检查（零成本）+ 可选 LLM 检查（仅在启发式标记时触发）。
集成到 fast_loop 评估后步骤，高分候选自动触发。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class DataLeakageResult:
    """数据泄漏检测结果."""

    has_leakage: bool
    reason: str
    confidence: str  # "high" / "medium" / "low"


class DataLeakageDetector:
    """数据泄漏检测器.

    两层检查:
    1. 启发式检查（零成本）: 完美分数、异常提升
    2. LLM 检查（可选）: 代码模式分析
    """

    def __init__(
        self,
        llm: object | None = None,
        *,
        perfect_score_threshold: float = 1.0,
        anomaly_multiplier: float = 10.0,
    ) -> None:
        self._llm = llm
        self._perfect_score_threshold = perfect_score_threshold
        self._anomaly_multiplier = anomaly_multiplier

    def check(
        self,
        code: str,
        task_desc: str,
        score: float,
        baseline_score: float = 0.0,
    ) -> DataLeakageResult:
        """检测数据泄漏.

        Args:
            code: 候选代码
            task_desc: 任务描述
            score: 候选分数
            baseline_score: 基线分数

        Returns:
            DataLeakageResult
        """
        # 1. 启发式检查
        heuristic = self._check_heuristic(score, baseline_score)
        if heuristic.has_leakage:
            return heuristic

        # 2. LLM 检查（仅在分数极高时触发，且有 LLM 可用）
        if score > 0.95 and self._llm is not None:
            llm_result = self._check_llm(code, task_desc, score)
            if llm_result.has_leakage:
                return llm_result

        return DataLeakageResult(has_leakage=False, reason="", confidence="low")

    def _check_heuristic(self, score: float, baseline_score: float) -> DataLeakageResult:
        """启发式检查 — 零成本快速判断."""
        # 完美分数
        if score >= self._perfect_score_threshold:
            return DataLeakageResult(
                has_leakage=True,
                reason=f"Perfect score ({score:.4f}) is suspicious",
                confidence="medium",
            )

        # 异常提升
        if baseline_score > 0 and score > baseline_score * self._anomaly_multiplier:
            return DataLeakageResult(
                has_leakage=True,
                reason=f"Score ({score:.4f}) is {score / baseline_score:.1f}x baseline ({baseline_score:.4f})",
                confidence="medium",
            )

        return DataLeakageResult(has_leakage=False, reason="", confidence="low")

    def _check_llm(self, code: str, task_desc: str, score: float) -> DataLeakageResult:
        """LLM 检查 — 代码模式分析."""
        try:
            from omnievolve.agents.llm_gateway import LLMGateway

            if not isinstance(self._llm, LLMGateway):
                return DataLeakageResult(has_leakage=False, reason="", confidence="low")

            prompt = f"""Analyze this code for potential data leakage.

Task: {task_desc[:500]}
Score achieved: {score:.4f}

Code (first 2000 chars):
{code[:2000]}

Check for:
1. Using test/validation data during training
2. Hardcoded expected outputs
3. Using global statistics computed on full dataset
4. Peeking at submission format for model selection

Respond with JSON: {{"has_leakage": bool, "reason": str, "confidence": "high"/"medium"/"low"}}"""

            response = self._llm.chat(
                messages=[{"role": "user", "content": prompt}],
                model="light",
                agent_role="critic",
            )

            from omnievolve.utils.response import extract_jsons

            jsons = extract_jsons(response.content)
            if jsons:
                d = jsons[0]
                return DataLeakageResult(
                    has_leakage=d.get("has_leakage", False),
                    reason=d.get("reason", ""),
                    confidence=d.get("confidence", "low"),
                )
        except Exception:
            logger.debug("LLM leakage check failed", exc_info=True)

        return DataLeakageResult(has_leakage=False, reason="", confidence="low")
