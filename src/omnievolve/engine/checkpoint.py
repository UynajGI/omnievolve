"""Checkpoint Manager — 提取自 EvolutionEngine.

T1 重构第四步：将检查点持久化/恢复逻辑从引擎中分离。
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from omnievolve.storage.db import Database

logger = logging.getLogger(__name__)


class CheckpointManager:
    """检查点持久化与恢复."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def save(
        self,
        experiment_id: str,
        generation: int,
        total_candidates: int,
        meta_scratchpad: str,
        failed_directions: list[str],
        recent_scores: list[float],
    ) -> None:
        """持久化易失状态到 experiment 表（崩溃恢复）."""
        checkpoint = {
            "generation": generation,
            "total_candidates": total_candidates,
            "meta_scratchpad": meta_scratchpad,
            "failed_directions": failed_directions,
            "recent_scores": recent_scores[-20:],
        }
        try:
            self._db.execute(
                "UPDATE experiment SET checkpoint_data = ? WHERE id = ?",
                (json.dumps(checkpoint, ensure_ascii=False), experiment_id),
            )
        except Exception:
            logger.warning("Failed to save checkpoint", exc_info=True)

    def load(self, experiment_id: str) -> dict:
        """从 experiment 表恢复易失状态.

        Returns:
            {"meta_scratchpad": ..., "failed_directions": ..., "recent_scores": ..., "total_candidates": ...}
            或空 dict（无检查点时）
        """
        try:
            row = self._db.fetchone(
                "SELECT checkpoint_data FROM experiment WHERE id = ?",
                (experiment_id,),
            )
            if row and row["checkpoint_data"]:
                checkpoint = json.loads(row["checkpoint_data"])
                logger.info(
                    "Checkpoint loaded: gen=%d, candidates=%d, scratchpad=%d chars",
                    checkpoint.get("generation", 0),
                    checkpoint.get("total_candidates", 0),
                    len(checkpoint.get("meta_scratchpad", "")),
                )
                return checkpoint
        except Exception:
            logger.debug("No checkpoint found (fresh experiment or v001 schema)", exc_info=True)
        return {}
