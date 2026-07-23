"""Candidate 图存储.

S4-14: 实现基础 GraphStore 与子图加载
- SQLite <-> NetworkX 双向同步
- 子图加载、停滞分支检测
- 设计文档 §7: add_candidate / add_reference_edge / update_search_state
"""

from __future__ import annotations

import json
import logging
from typing import Any

import networkx as nx

from omnievolve.storage.db import Database
from omnievolve.storage.repositories.base import generate_id, now_iso

logger = logging.getLogger(__name__)


class GraphStore:
    """SQLite Candidate 图 ↔ NetworkX 内存图双向同步."""

    def __init__(self, db: Database) -> None:
        self._db = db

    # ─── 设计文档 §7 写方法 ───────────────────────────────────────────

    def add_candidate(self, candidate: dict, parents: list[dict]) -> str:
        """单事务插入 Candidate、多父代 Lineage、初始 SearchState 和 Outbox.

        Args:
            candidate: 候选字段字典 (experiment_id, task_id, generation,
                       artifact_hash, search_policy_id, island_id, meta, ...)
            parents: [{"id": ..., "relation_type": ...}, ...]

        Returns:
            新候选 ID
        """
        candidate_id = candidate.get("id") or generate_id()
        meta = candidate.get("meta")

        with self._db.transaction() as conn:
            conn.execute(
                """
                INSERT INTO candidate
                    (id, experiment_id, task_id, generation, island_id,
                     artifact_hash, search_policy_id, status, meta)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    candidate_id,
                    candidate.get("experiment_id", ""),
                    candidate.get("task_id", ""),
                    candidate.get("generation", 0),
                    candidate.get("island_id"),
                    candidate.get("artifact_hash", ""),
                    candidate.get("search_policy_id", "default"),
                    candidate.get("status", "pending"),
                    json.dumps(meta) if meta else None,
                ),
            )

            # 初始搜索状态
            conn.execute(
                "INSERT INTO candidate_search_state (candidate_id) VALUES (?)",
                (candidate_id,),
            )

            # 多父代血缘
            for order, parent in enumerate(parents):
                conn.execute(
                    """
                    INSERT OR IGNORE INTO candidate_lineage
                        (child_id, parent_id, relation_type, parent_order)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        candidate_id,
                        parent["id"],
                        parent.get("relation_type", "mutation"),
                        order,
                    ),
                )

            # Outbox 通知（向量索引最终一致性）
            conn.execute(
                """
                INSERT OR IGNORE INTO vector_index_job
                    (entity_type, entity_id, embedding_profile_id, content_hash, operation, status)
                VALUES (?, ?, ?, ?, 'upsert', 'pending')
                """,
                (
                    "candidate",
                    candidate_id,
                    "profile-code-default",
                    candidate.get("artifact_hash", ""),
                ),
            )

        logger.debug("GraphStore.add_candidate: %s", candidate_id)
        return candidate_id

    def add_reference_edge(
        self,
        src: str,
        dst: str,
        reference_type: str,
        detail: dict | None = None,
    ) -> None:
        """添加引用边（非血缘）.

        Reference Edge 表示生成时借鉴/检索/修复引用了哪些历史候选，
        区别于 Lineage Edge（真正遗传关系）。
        """
        self._db.execute(
            """
            INSERT OR IGNORE INTO candidate_reference_edge
                (src_candidate_id, dst_candidate_id, reference_type, detail)
            VALUES (?, ?, ?, ?)
            """,
            (src, dst, reference_type, json.dumps(detail) if detail else None),
        )

    def update_search_state(self, candidate_id: str, delta: dict) -> None:
        """更新候选搜索状态（MCTS 统计量）.

        Args:
            delta: 可包含 visit_count, value_sum, selection_count,
                   offspring_count, frontier_status 等键。
        """
        updates = ["updated_at = ?"]
        params: list[Any] = [now_iso()]

        if "visit_count" in delta:
            updates.append("visit_count = visit_count + ?")
            params.append(delta["visit_count"])
        if "value_sum" in delta:
            updates.append("value_sum = value_sum + ?")
            params.append(delta["value_sum"])
        if "selection_count" in delta:
            updates.append("selection_count = selection_count + ?")
            params.append(delta["selection_count"])
        if "offspring_count" in delta:
            updates.append("offspring_count = offspring_count + ?")
            params.append(delta["offspring_count"])
        if "frontier_status" in delta:
            updates.append("frontier_status = ?")
            params.append(delta["frontier_status"])

        params.append(candidate_id)
        self._db.execute(
            f"UPDATE candidate_search_state SET {', '.join(updates)} WHERE candidate_id = ?",
            tuple(params),
        )

    # ─── 读方法 ────────────────────────────────────────────────────────

    def load_subgraph(
        self,
        experiment_id: str,
        root_ids: list[str] | None = None,
        max_depth: int = 10,
        include_reference_edges: bool = False,
    ) -> nx.MultiDiGraph:
        """加载子图到 NetworkX.

        Args:
            experiment_id: 实验 ID
            root_ids: 根节点列表（None 表示所有）
            max_depth: 最大深度
            include_reference_edges: 是否包含引用边

        Returns:
            NetworkX MultiDiGraph
        """
        G = nx.MultiDiGraph()

        # 加载候选节点
        if root_ids:
            placeholders = ",".join(["?"] * len(root_ids))
            rows = self._db.fetchall(
                f"""
                SELECT c.*, css.visit_count, css.value_sum, css.frontier_status
                FROM candidate c
                LEFT JOIN candidate_search_state css ON c.id = css.candidate_id
                WHERE c.experiment_id = ? AND c.id IN ({placeholders})
                """,
                (experiment_id, *root_ids),
            )
        else:
            rows = self._db.fetchall(
                """
                SELECT c.*, css.visit_count, css.value_sum, css.frontier_status
                FROM candidate c
                LEFT JOIN candidate_search_state css ON c.id = css.candidate_id
                WHERE c.experiment_id = ?
                """,
                (experiment_id,),
            )

        for row in rows:
            G.add_node(
                row["id"],
                generation=row["generation"],
                status=row["status"],
                island_id=row["island_id"],
                visit_count=row["visit_count"] or 0,
                value_sum=row["value_sum"] or 0,
                frontier_status=row["frontier_status"] or "open",
            )

        # 加载血缘边
        node_ids = set(G.nodes())
        if node_ids:
            placeholders = ",".join(["?"] * len(node_ids))
            edges = self._db.fetchall(
                f"""
                SELECT child_id, parent_id, relation_type, parent_order
                FROM candidate_lineage
                WHERE child_id IN ({placeholders})
                """,
                tuple(node_ids),
            )

            for edge in edges:
                if edge["parent_id"] in node_ids:
                    G.add_edge(
                        edge["parent_id"],
                        edge["child_id"],
                        relation_type=edge["relation_type"],
                        parent_order=edge["parent_order"],
                        edge_kind="lineage",
                    )

        # 加载引用边
        if include_reference_edges and node_ids:
            ref_edges = self._db.fetchall(
                f"""
                SELECT src_candidate_id, dst_candidate_id, reference_type
                FROM candidate_reference_edge
                WHERE src_candidate_id IN ({placeholders})
                """,
                tuple(node_ids),
            )

            for edge in ref_edges:
                if edge["dst_candidate_id"] in node_ids:
                    G.add_edge(
                        edge["src_candidate_id"],
                        edge["dst_candidate_id"],
                        reference_type=edge["reference_type"],
                        edge_kind="reference",
                    )

        return G

    def get_stagnant_branches(
        self,
        experiment_id: str,
        threshold_gens: int,
    ) -> list[str]:
        """检测停滞分支.

        返回连续 threshold_gens 代没有改进的分支根节点。
        """
        # 获取每代的最佳分数
        rows = self._db.fetchall(
            """
            SELECT c.generation, MAX(er.primary_score) as best_score
            FROM candidate c
            JOIN evaluation_run er ON c.id = er.candidate_id
            WHERE c.experiment_id = ? AND er.status = 'completed' AND er.passed = 1
            GROUP BY c.generation
            ORDER BY c.generation
            """,
            (experiment_id,),
        )

        if len(rows) < threshold_gens:
            return []

        # 检测停滞
        stagnant = []
        for i in range(len(rows) - threshold_gens):
            window = rows[i : i + threshold_gens]
            scores = [r["best_score"] for r in window if r["best_score"] is not None]
            if scores and max(scores) - min(scores) < 0.001:
                stagnant.append(f"gen_{window[0]['generation']}")

        return stagnant

    def get_best_paths(
        self,
        experiment_id: str,
        evaluator_version_id: str,
        environment_version_id: str,
        top_k: int = 1,
    ) -> list[list[str]]:
        """获取最佳贡献路径.

        在多父代 DAG 中返回最优贡献路径。
        """
        G = self.load_subgraph(experiment_id)

        # 获取每个节点的分数
        scores = self._get_candidate_scores(
            experiment_id, evaluator_version_id, environment_version_id
        )

        # 找到分数最高的节点
        if not scores:
            return []

        sorted_candidates = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        paths = []

        for candidate_id, _ in sorted_candidates[:top_k]:
            if candidate_id not in G:
                continue

            # 回溯到根节点
            path = self._trace_best_path(G, candidate_id, scores)
            paths.append(path)

        return paths

    def get_diverse_elites(
        self,
        experiment_id: str,
        island_id: str | None = None,
        top_k: int = 5,
    ) -> list[str]:
        """获取多样化的精英候选.

        基于岛屿和血缘距离选择多样化的高分候选。
        """
        # 获取高分候选
        if island_id:
            rows = self._db.fetchall(
                """
                SELECT c.id, er.primary_score
                FROM candidate c
                JOIN evaluation_run er ON c.id = er.candidate_id
                WHERE c.experiment_id = ? AND c.island_id = ?
                  AND er.status = 'completed' AND er.passed = 1
                ORDER BY er.primary_score DESC
                LIMIT ?
                """,
                (experiment_id, island_id, top_k * 2),
            )
        else:
            rows = self._db.fetchall(
                """
                SELECT c.id, er.primary_score
                FROM candidate c
                JOIN evaluation_run er ON c.id = er.candidate_id
                WHERE c.experiment_id = ?
                  AND er.status = 'completed' AND er.passed = 1
                ORDER BY er.primary_score DESC
                LIMIT ?
                """,
                (experiment_id, top_k * 2),
            )

        # 简单多样化：按岛屿分组
        selected: list[Any] = []
        seen_islands = set()

        for row in rows:
            candidate = self._db.fetchone(
                "SELECT island_id FROM candidate WHERE id = ?", (row["id"],)
            )
            island = candidate["island_id"] if candidate else None

            if island not in seen_islands or len(selected) < top_k:
                selected.append(row["id"])
                seen_islands.add(island)

            if len(selected) >= top_k:
                break

        return selected[:top_k]

    def export_graphml(self, experiment_id: str, path: str) -> None:
        """导出 GraphML."""
        G = self.load_subgraph(experiment_id, include_reference_edges=True)
        nx.write_graphml(G, path)
        logger.info(f"Exported graph to {path}")

    def _get_candidate_scores(
        self,
        experiment_id: str,
        evaluator_version_id: str,
        environment_version_id: str,
    ) -> dict[str, float]:
        """获取候选分数映射."""
        rows = self._db.fetchall(
            """
            SELECT candidate_id, MAX(primary_score) as score
            FROM evaluation_run
            WHERE experiment_id = ?
              AND evaluator_version_id = ?
              AND environment_version_id = ?
              AND status = 'completed'
            GROUP BY candidate_id
            """,
            (experiment_id, evaluator_version_id, environment_version_id),
        )
        return {row["candidate_id"]: row["score"] for row in rows if row["score"]}

    def _trace_best_path(
        self,
        G: nx.MultiDiGraph,
        target_id: str,
        scores: dict[str, float],
    ) -> list[str]:
        """回溯最佳路径."""
        path = [target_id]
        current = target_id

        while True:
            # 获取父代
            predecessors = list(G.predecessors(current))
            if not predecessors:
                break

            # 选择分数最高的父代
            best_parent = max(
                predecessors,
                key=lambda p: scores.get(p, 0),
            )
            path.append(best_parent)
            current = best_parent

        path.reverse()
        return path
