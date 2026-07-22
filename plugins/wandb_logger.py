"""W&B 实验追踪.

从 ShinkaEvolve wandb_logging.py 移植，适配 OmniEvolve。
延迟导入 wandb，best-effort 日志，失败不阻断。
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class OmniEvolveWandbLogger:
    """Weights & Biases 日志记录器.

    所有方法 try/except 包裹，失败时 logger.warning 不阻断进化流程。
    """

    def __init__(
        self,
        *,
        project: str = "omnievolve",
        entity: str | None = None,
        group: str | None = None,
        tags: list[str] | None = None,
        config: dict | None = None,
        enabled: bool = True,
    ) -> None:
        self._project = project
        self._entity = entity
        self._group = group
        self._tags = tags or []
        self._config = config or {}
        self._enabled = enabled
        self._wandb: Any = None
        self._run: Any = None

    def start(self, experiment_id: str) -> None:
        """初始化 W&B run."""
        if not self._enabled:
            return
        try:
            import wandb

            self._wandb = wandb
            self._run = wandb.init(
                project=self._project,
                entity=self._entity,
                group=self._group,
                tags=self._tags + [experiment_id[:12]],
                config={**self._config, "experiment_id": experiment_id},
                reinit=True,
            )
            logger.info("W&B run started: %s", self._run.url)
        except Exception:
            logger.warning("Failed to start W&B run, continuing without tracking", exc_info=True)
            self._enabled = False

    def log_candidate(
        self,
        candidate_id: str,
        generation: int,
        score: float | None,
        cost_usd: float = 0.0,
        token_cost: int = 0,
        **extra: Any,
    ) -> None:
        """记录单个候选的指标."""
        if not self._enabled or self._wandb is None:
            return
        try:
            metrics: dict[str, Any] = {
                "candidate/score": score or 0.0,
                "candidate/generation": generation,
                "candidate/cost_usd": cost_usd,
                "candidate/tokens": token_cost,
            }
            metrics.update(extra)
            self._wandb.log(metrics, step=generation)
        except Exception:
            logger.debug("Failed to log candidate to W&B", exc_info=True)

    def log_generation_summary(
        self,
        generation: int,
        best_score: float | None,
        avg_score: float | None,
        total_cost: float,
        total_candidates: int,
    ) -> None:
        """记录每代摘要."""
        if not self._enabled or self._wandb is None:
            return
        try:
            self._wandb.log(
                {
                    "generation/best_score": best_score or 0.0,
                    "generation/avg_score": avg_score or 0.0,
                    "generation/cumulative_cost": total_cost,
                    "generation/total_candidates": total_candidates,
                },
                step=generation,
            )
        except Exception:
            logger.debug("Failed to log generation summary to W&B", exc_info=True)

    def log_final(
        self,
        best_score: float | None,
        total_candidates: int,
        total_cost: float,
        total_tokens: int,
    ) -> None:
        """记录最终摘要."""
        if not self._enabled or self._wandb is None:
            return
        try:
            self._wandb.summary["final/best_score"] = best_score or 0.0
            self._wandb.summary["final/total_candidates"] = total_candidates
            self._wandb.summary["final/total_cost"] = total_cost
            self._wandb.summary["final/total_tokens"] = total_tokens
        except Exception:
            logger.debug("Failed to log final summary to W&B", exc_info=True)

    def finish(self) -> None:
        """关闭 W&B run."""
        if not self._enabled or self._wandb is None:
            return
        try:
            self._wandb.finish()
        except Exception:
            logger.debug("Failed to finish W&B run", exc_info=True)
