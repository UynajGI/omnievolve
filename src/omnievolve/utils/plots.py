"""图表可视化套件.

从 ShinkaEvolve plots/ 移植 4 个核心图表，适配 OmniEvolve 表结构。
matplotlib 为可选依赖（omnievolve[plots]）。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from omnievolve.storage.db import Database

logger = logging.getLogger(__name__)


def _get_figure_and_axes():
    """延迟导入 matplotlib 并返回 Figure/Axes."""
    import matplotlib.pyplot as plt

    return plt, plt.figure(), plt.gca()


def plot_fitness_history(experiment_id: str, db: Database):  # type: ignore[type-arg]
    """绘制分数随 generation 演进图.

    X 轴: generation
    Y 轴: best_score / avg_score per generation
    """
    import pandas as pd

    plt, fig, ax = _get_figure_and_axes()

    rows = db.fetchall(
        """
        SELECT generation, MAX(score) as best_score, AVG(score) as avg_score
        FROM candidate
        WHERE experiment_id = ? AND score IS NOT NULL
        GROUP BY generation ORDER BY generation ASC
        """,
        (experiment_id,),
    )

    if not rows:
        ax.text(0.5, 0.5, "No data", ha="center", va="center")
        return fig

    df = pd.DataFrame(rows)

    ax.plot(df["generation"], df["best_score"], "b-o", label="Best Score", markersize=4)
    ax.plot(df["generation"], df["avg_score"], "r--s", label="Avg Score", markersize=3, alpha=0.7)
    ax.set_xlabel("Generation")
    ax.set_ylabel("Score")
    ax.set_title(f"Fitness History — {experiment_id[:12]}...")
    ax.legend()
    ax.grid(True, alpha=0.3)

    fig.tight_layout()
    return fig


def plot_cost_curve(experiment_id: str, db: Database):  # type: ignore[type-arg]
    """绘制累积 API 成本曲线."""
    import pandas as pd

    plt, fig, ax = _get_figure_and_axes()

    rows = db.fetchall(
        """
        SELECT
            DATE(created_at) as date,
            SUM(cost_usd) as daily_cost,
            SUM(input_tokens + output_tokens) as daily_tokens
        FROM llm_call_ledger
        WHERE experiment_id = ?
        GROUP BY DATE(created_at)
        ORDER BY DATE(created_at) ASC
        """,
        (experiment_id,),
    )

    if not rows:
        ax.text(0.5, 0.5, "No cost data", ha="center", va="center")
        return fig

    df = pd.DataFrame(rows)
    df["cumulative_cost"] = df["daily_cost"].cumsum()

    ax.fill_between(range(len(df)), 0, df["cumulative_cost"], alpha=0.3, color="green")
    ax.plot(range(len(df)), df["cumulative_cost"], "g-", linewidth=2)
    ax.set_xlabel("Day")
    ax.set_ylabel("Cumulative Cost (USD)")
    ax.set_title(f"Cost Curve — {experiment_id[:12]}...")
    ax.grid(True, alpha=0.3)

    fig.tight_layout()
    return fig


def plot_lineage_tree(experiment_id: str, db: Database):  # type: ignore[type-arg]
    """绘制进化谱系树."""
    plt, fig, ax = _get_figure_and_axes()

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
        ax.text(0.5, 0.5, "No lineage data", ha="center", va="center")
        return fig

    # 层级布局
    gen_candidates: dict[int, list[dict]] = {}
    for row in rows:
        gen = row["generation"]
        if gen not in gen_candidates:
            gen_candidates[gen] = []
        gen_candidates[gen].append(dict(row))

    max_gen = max(gen_candidates.keys())
    for gen, candidates in gen_candidates.items():
        n = len(candidates)
        for i, cand in enumerate(candidates):
            x = (i + 0.5) / max(n, 1)
            y = 1.0 - gen / max(max_gen, 1)
            score = cand["score"] or 0
            color = "green" if cand["status"] == "evaluated" else "gray"
            ax.scatter(x, y, c=color, s=30 + score * 100, zorder=5, alpha=0.8)

            # 绘制到父代的连线
            parent_raw = cand["parent_ids"] or ""
            parent_list = [p.strip() for p in parent_raw.split(",") if p.strip()]
            for pid in parent_list:
                parent = next(
                    (c for cands in gen_candidates.values() for c in cands if c["id"] == pid),
                    None,
                )
                if parent:
                    p_gen = parent["generation"]
                    p_idx = next(
                        (i for i, c in enumerate(gen_candidates.get(p_gen, [])) if c["id"] == pid),
                        0,
                    )
                    p_n = len(gen_candidates.get(p_gen, [parent]))
                    p_x = (p_idx + 0.5) / max(p_n, 1)
                    p_y = 1.0 - p_gen / max(max_gen, 1)
                    ax.plot([p_x, x], [p_y, y], "k-", alpha=0.2, linewidth=0.5)

    ax.set_xlim(-0.05, 1.05)
    ax.set_ylim(-0.05, 1.05)
    ax.set_xlabel("Position within generation")
    ax.set_ylabel("Generation (top=oldest)")
    ax.set_title(f"Lineage Tree — {experiment_id[:12]}...")
    ax.set_xticks([])
    ax.set_yticks([])

    fig.tight_layout()
    return fig


def plot_pareto_front(experiment_id: str, db: Database):  # type: ignore[type-arg]
    """绘制性能 vs 成本 Pareto 前沿."""
    import pandas as pd

    plt, fig, ax = _get_figure_and_axes()

    rows = db.fetchall(
        """
        SELECT
            c.id, c.score, c.generation,
            COALESCE(SUM(llm.cost_usd), 0) as cost,
            COALESCE(SUM(llm.input_tokens + llm.output_tokens), 0) as tokens
        FROM candidate c
        LEFT JOIN llm_call_ledger llm ON llm.candidate_id = c.id
        WHERE c.experiment_id = ? AND c.score IS NOT NULL
        GROUP BY c.id
        ORDER BY c.generation ASC
        """,
        (experiment_id,),
    )

    if not rows:
        ax.text(0.5, 0.5, "No data", ha="center", va="center")
        return fig

    df = pd.DataFrame(rows)

    scatter = ax.scatter(
        df["cost"],
        df["score"],
        c=df["generation"],
        cmap="viridis",
        s=50,
        alpha=0.7,
        edgecolors="black",
        linewidth=0.5,
    )

    # 标注最佳
    best_idx = df["score"].idxmax()
    best = df.loc[best_idx]
    ax.annotate(
        f"Best: {best['score']:.4f}",
        xy=(best["cost"], best["score"]),
        xytext=(10, -10),
        textcoords="offset points",
        arrowprops={"arrowstyle": "->", "color": "red"},
        fontsize=8,
        color="red",
    )

    ax.set_xlabel("Cost (USD)")
    ax.set_ylabel("Score")
    ax.set_title(f"Pareto Front — {experiment_id[:12]}...")
    plt.colorbar(scatter, label="Generation")
    ax.grid(True, alpha=0.3)

    fig.tight_layout()
    return fig


def save_all_plots(experiment_id: str, db: Database, output_dir: str = ".") -> None:  # type: ignore[type-arg]
    """保存全部 4 个图表到指定目录."""
    import os

    os.makedirs(output_dir, exist_ok=True)

    plots = [
        ("fitness_history", plot_fitness_history),
        ("cost_curve", plot_cost_curve),
        ("lineage_tree", plot_lineage_tree),
        ("pareto_front", plot_pareto_front),
    ]

    for name, func in plots:
        try:
            fig = func(experiment_id, db)
            path = os.path.join(output_dir, f"{name}.png")
            fig.savefig(path, dpi=150, bbox_inches="tight")
            logger.info("Saved %s", path)
        except Exception:
            logger.warning("Failed to generate %s", name, exc_info=True)
