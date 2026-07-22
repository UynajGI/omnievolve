"""数据库导出为 DataFrame.

从 ShinkaEvolve load_df.py 移植，适配 OmniEvolve 表结构。
支持将候选/评估/谱系数据导出为 pandas DataFrame。
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from omnievolve.storage.db import Database

logger = logging.getLogger(__name__)


def export_candidates(experiment_id: str, db: Database):  # type: ignore[type-arg]
    """导出候选 + 评估结果为 DataFrame.

    Returns:
        pd.DataFrame with columns: id, generation, score, status, passed,
        parent_ids, model, token_cost, eval_time_ms, created_at
    """
    import pandas as pd

    rows = db.fetchall(
        """
        SELECT
            c.id, c.generation, c.score, c.status,
            c.parent_ids, c.meta, c.created_at,
            er.id as eval_run_id, er.passed, er.metrics,
            llm.model, llm.input_tokens, llm.output_tokens, llm.cost_usd
        FROM candidate c
        LEFT JOIN evaluation_run er ON er.candidate_id = c.id
        LEFT JOIN llm_call_ledger llm ON llm.candidate_id = c.id
        WHERE c.experiment_id = ?
        ORDER BY c.generation ASC, c.created_at ASC
        """,
        (experiment_id,),
    )

    records: list[dict] = []
    for row in rows:
        meta = {}
        if row["meta"]:
            try:
                meta = json.loads(row["meta"]) if isinstance(row["meta"], str) else row["meta"]
            except (json.JSONDecodeError, TypeError):
                pass

        metrics = {}
        if row["metrics"]:
            try:
                metrics = json.loads(row["metrics"]) if isinstance(row["metrics"], str) else row["metrics"]
            except (json.JSONDecodeError, TypeError):
                pass

        records.append(
            {
                "id": row["id"],
                "generation": row["generation"],
                "score": row["score"],
                "status": row["status"],
                "passed": bool(row["passed"]) if row["passed"] is not None else None,
                "parent_ids": row["parent_ids"],
                "model": row["model"] or meta.get("model", ""),
                "token_cost": (row["input_tokens"] or 0) + (row["output_tokens"] or 0),
                "cost_usd": row["cost_usd"] or 0.0,
                "eval_time_ms": metrics.get("execution_time_ms", 0),
                "thought": meta.get("thought", "")[:200],
                "created_at": row["created_at"],
            }
        )

    return pd.DataFrame(records)


def export_lineage(experiment_id: str, db: Database):  # type: ignore[type-arg]
    """导出谱系关系为 DataFrame.

    Returns:
        pd.DataFrame with columns: id, parent_ids, generation, score, depth
    """
    import pandas as pd

    rows = db.fetchall(
        """
        SELECT id, parent_ids, generation, score
        FROM candidate
        WHERE experiment_id = ?
        ORDER BY generation ASC
        """,
        (experiment_id,),
    )

    records: list[dict] = []
    for row in rows:
        parent_raw = row["parent_ids"] or ""
        parent_list = [p.strip() for p in parent_raw.split(",") if p.strip()]
        records.append(
            {
                "id": row["id"],
                "parent_ids": parent_raw,
                "num_parents": len(parent_list),
                "generation": row["generation"],
                "score": row["score"],
            }
        )

    return pd.DataFrame(records)


def get_path_to_best(experiment_id: str, db: Database) -> list[str]:
    """获取最佳候选的祖先链.

    Returns:
        从根到最佳候选的 candidate_id 列表
    """
    best = db.fetchone(
        """
        SELECT id, parent_ids, score
        FROM candidate
        WHERE experiment_id = ? AND score IS NOT NULL
        ORDER BY score DESC LIMIT 1
        """,
        (experiment_id,),
    )

    if best is None:
        return []

    path: list[str] = [best["id"]]
    current = best

    visited: set[str] = {best["id"]}

    while current and current["parent_ids"]:
        parent_raw = current["parent_ids"]
        parent_list = [p.strip() for p in parent_raw.split(",") if p.strip()]
        if not parent_list:
            break

        parent_id = parent_list[0]
        if parent_id in visited:
            break
        visited.add(parent_id)

        parent = db.fetchone(
            "SELECT id, parent_ids FROM candidate WHERE id = ?",
            (parent_id,),
        )
        if parent is None:
            break

        path.append(parent["id"])
        current = parent

    path.reverse()
    return path


def export_experiment_summary(experiment_id: str, db: Database) -> dict:  # type: ignore[type-arg]
    """导出实验摘要统计.

    Returns:
        dict with total_candidates, best_score, avg_score, total_cost, generations
    """
    row = db.fetchone(
        """
        SELECT
            COUNT(*) as total_candidates,
            MAX(score) as best_score,
            AVG(score) as avg_score,
            MAX(generation) as max_gen,
            MIN(generation) as min_gen
        FROM candidate
        WHERE experiment_id = ? AND score IS NOT NULL
        """,
        (experiment_id,),
    )

    cost_row = db.fetchone(
        """
        SELECT SUM(cost_usd) as total_cost, SUM(input_tokens + output_tokens) as total_tokens
        FROM llm_call_ledger
        WHERE experiment_id = ?
        """,
        (experiment_id,),
    )

    return {
        "experiment_id": experiment_id,
        "total_candidates": row["total_candidates"] if row else 0,
        "best_score": row["best_score"] if row else None,
        "avg_score": row["avg_score"] if row else None,
        "total_generations": (row["max_gen"] - row["min_gen"] + 1) if row and row["max_gen"] else 0,
        "total_cost_usd": cost_row["total_cost"] if cost_row else 0.0,
        "total_tokens": cost_row["total_tokens"] if cost_row else 0,
    }
