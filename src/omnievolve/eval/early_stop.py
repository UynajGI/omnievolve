"""评估早停 — 统计置信度提前终止.

从 ShinkaEvolve eval_stop.py 移植。
在少量 trial 后根据统计置信度判断是否提前终止评估。
"""

from __future__ import annotations

import functools
import logging
import math
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal

logger = logging.getLogger(__name__)


@functools.cache
def _sp_stats():
    """Lazy import scipy."""
    from scipy import stats

    return stats


@dataclass
class EarlyStopDecision:
    """早停检查结果."""

    should_stop: bool
    prediction: Literal["beats", "fails", "uncertain"]
    confidence: float
    trials_used: int
    reason: str | None = None


class EarlyStopMethod(ABC):
    """早停方法基类."""

    @abstractmethod
    def check(
        self, scores: list[float], threshold: float
    ) -> EarlyStopDecision:
        """检查是否应提前停止.

        Args:
            scores: 已观察到的分数列表
            threshold: 要超过的目标阈值

        Returns:
            EarlyStopDecision
        """


class BayesianEarlyStop(EarlyStopMethod):
    """贝叶斯早停 — 基于后验概率判断."""

    def __init__(
        self,
        prob_cutoff: float = 0.95,
        min_trials: int = 3,
    ) -> None:
        self._prob_cutoff = prob_cutoff
        self._min_trials = min_trials

    def check(self, scores: list[float], threshold: float) -> EarlyStopDecision:
        n = len(scores)
        if n < self._min_trials:
            return EarlyStopDecision(
                should_stop=False,
                prediction="uncertain",
                confidence=0.0,
                trials_used=n,
                reason=f"Only {n} trials (< min {self._min_trials})",
            )

        try:
            stats = _sp_stats()
            mean = sum(scores) / n
            if n > 1:
                std = math.sqrt(sum((s - mean) ** 2 for s in scores) / (n - 1))
            else:
                std = 0.0

            # t 分布的 CDF
            if std > 0:
                t_stat = (mean - threshold) / (std / math.sqrt(n))
                cdf = stats.t.cdf(t_stat, df=n - 1)
            else:
                cdf = 1.0 if mean >= threshold else 0.0

            if cdf >= self._prob_cutoff:
                return EarlyStopDecision(
                    should_stop=True,
                    prediction="beats",
                    confidence=cdf,
                    trials_used=n,
                    reason=f"P(mean > threshold) = {cdf:.3f} >= {self._prob_cutoff}",
                )
            if (1 - cdf) >= self._prob_cutoff:
                return EarlyStopDecision(
                    should_stop=True,
                    prediction="fails",
                    confidence=1 - cdf,
                    trials_used=n,
                    reason=f"P(mean < threshold) = {1 - cdf:.3f} >= {self._prob_cutoff}",
                )
        except ImportError:
            logger.debug("scipy not available, skipping Bayesian early stop")
        except Exception:
            logger.debug("Bayesian early stop calculation failed", exc_info=True)

        return EarlyStopDecision(
            should_stop=False,
            prediction="uncertain",
            confidence=0.0,
            trials_used=n,
        )


class ConfidenceIntervalEarlyStop(EarlyStopMethod):
    """置信区间早停 — 基于置信区间宽度."""

    def __init__(
        self,
        ci_confidence: float = 0.90,
        min_trials: int = 3,
    ) -> None:
        self._ci_confidence = ci_confidence
        self._min_trials = min_trials

    def check(self, scores: list[float], threshold: float) -> EarlyStopDecision:
        n = len(scores)
        if n < self._min_trials:
            return EarlyStopDecision(
                should_stop=False, prediction="uncertain", confidence=0.0, trials_used=n
            )

        try:
            stats = _sp_stats()
            mean = sum(scores) / n
            if n > 1:
                std = math.sqrt(sum((s - mean) ** 2 for s in scores) / (n - 1))
            else:
                std = 0.0

            alpha = 1 - self._ci_confidence
            t_crit = stats.t.ppf(1 - alpha / 2, df=n - 1)
            margin = t_crit * std / math.sqrt(n) if std > 0 else 0.0

            ci_lower = mean - margin
            ci_upper = mean + margin

            if ci_lower > threshold:
                return EarlyStopDecision(
                    should_stop=True,
                    prediction="beats",
                    confidence=self._ci_confidence,
                    trials_used=n,
                    reason=f"CI lower ({ci_lower:.4f}) > threshold ({threshold:.4f})",
                )
            if ci_upper < threshold:
                return EarlyStopDecision(
                    should_stop=True,
                    prediction="fails",
                    confidence=self._ci_confidence,
                    trials_used=n,
                    reason=f"CI upper ({ci_upper:.4f}) < threshold ({threshold:.4f})",
                )
        except ImportError:
            logger.debug("scipy not available, skipping CI early stop")
        except Exception:
            logger.debug("CI early stop calculation failed", exc_info=True)

        return EarlyStopDecision(
            should_stop=False, prediction="uncertain", confidence=0.0, trials_used=n
        )


class HybridEarlyStop(EarlyStopMethod):
    """混合早停 — Bayesian + CI 取并集."""

    def __init__(
        self,
        prob_cutoff: float = 0.95,
        ci_confidence: float = 0.90,
        min_trials: int = 3,
    ) -> None:
        self._bayesian = BayesianEarlyStop(prob_cutoff=prob_cutoff, min_trials=min_trials)
        self._ci = ConfidenceIntervalEarlyStop(
            ci_confidence=ci_confidence, min_trials=min_trials
        )

    def check(self, scores: list[float], threshold: float) -> EarlyStopDecision:
        bayes = self._bayesian.check(scores, threshold)
        if bayes.should_stop:
            return bayes
        ci = self._ci.check(scores, threshold)
        return ci


def create_early_stop_method(
    method: str = "none",
    **kwargs: float,
) -> EarlyStopMethod | None:
    """工厂函数 — 创建早停方法.

    Args:
        method: "none" / "bayesian" / "ci" / "hybrid"
        **kwargs: 传递给具体方法的参数

    Returns:
        EarlyStopMethod or None (method="none" 时)
    """
    if method == "none":
        return None
    if method == "bayesian":
        return BayesianEarlyStop(**kwargs)
    if method == "ci":
        return ConfidenceIntervalEarlyStop(**kwargs)
    if method == "hybrid":
        return HybridEarlyStop(**kwargs)
    logger.warning("Unknown early stop method: %s, disabling", method)
    return None
