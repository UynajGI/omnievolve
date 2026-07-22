"""可视化工具 — 候选进化树渲染.

从 MLEvolve utils/visualization.py 移植，适配 OmniEvolve 数据模型。
独立工具，仅用于 CLI/调试，不集成到进化流程。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from omnievolve.storage.db import Database


def candidate_tree_to_rich(experiment_id: str, db: Database) -> str:
    """将实验候选树渲染为 Rich Tree 风格的文本.

    使用 ASCII 树形结构展示候选的父子关系和分数。

    Returns:
        树形结构的纯文本字符串
    """
    rows = db.fetchall(
        """
        SELECT id, parent_ids, generation, score, status
        FROM candidate
        WHERE experiment_id = ?
        ORDER BY generation ASC, created_at ASC
        """,
        (experiment_id,),
    )

    if not rows:
        return "No candidates found."

    # 构建 parent -> children 映射
    children: dict[str, list[dict]] = {}
    roots: list[dict] = []
    candidates: dict[str, dict] = {}

    for row in rows:
        cand = {
            "id": row["id"][:8],
            "full_id": row["id"],
            "generation": row["generation"],
            "score": row["score"],
            "status": row["status"],
        }
        candidates[row["id"]] = cand

        parent_ids_raw = row["parent_ids"] or ""
        parent_id_list = [p.strip() for p in parent_ids_raw.split(",") if p.strip()]

        if not parent_id_list:
            roots.append(cand)
        else:
            for pid in parent_id_list:
                if pid not in children:
                    children[pid] = []
                children[pid].append(cand)

    # 递归渲染
    lines: list[str] = [f"Evolution Tree for experiment {experiment_id[:12]}..."]

    def render(node: dict, prefix: str, is_last: bool) -> None:
        connector = "└── " if is_last else "├── "
        score_str = f"score={node['score']:.4f}" if node["score"] is not None else "no score"
        line = f"{prefix}{connector}[gen {node['generation']}] {node['id']} ({score_str}) [{node['status']}]"
        lines.append(line)
        child_prefix = prefix + ("    " if is_last else "│   ")
        child_list = children.get(node["full_id"], [])
        for i, child in enumerate(child_list):
            render(child, child_prefix, i == len(child_list) - 1)

    for i, root in enumerate(roots):
        render(root, "", i == len(roots) - 1)

    return "\n".join(lines)


def candidate_tree_to_string(experiment_id: str, db: Database) -> str:
    """将实验候选树渲染为纯文本摘要."""
    rows = db.fetchall(
        """
        SELECT generation, COUNT(*) as cnt, MAX(score) as best_score
        FROM candidate
        WHERE experiment_id = ?
        GROUP BY generation
        ORDER BY generation ASC
        """,
        (experiment_id,),
    )

    if not rows:
        return "No candidates found."

    lines: list[str] = [f"Evolution Summary for {experiment_id[:12]}...", ""]
    lines.append(f"{'Gen':>4} | {'Count':>5} | {'Best Score':>10} | Progress")
    lines.append("-" * 50)

    max_score = max((row["best_score"] or 0) for row in rows)
    for row in rows:
        gen = row["generation"]
        cnt = row["cnt"]
        best = row["best_score"] or 0
        bar_len = int(best / max(max_score, 0.001) * 20)
        bar = "█" * bar_len + "░" * (20 - bar_len)
        lines.append(f"{gen:>4} | {cnt:>5} | {best:>10.4f} | {bar}")

    return "\n".join(lines)
