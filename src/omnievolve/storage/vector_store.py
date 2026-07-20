"""混合检索器 - FTS5 + Vector + scope filter + rerank.

S6-11: 实现 FTS5 文档与作用域索引
S6-12: 实现 Hybrid Retriever 与融合排序
S6-13: 实现 code/thought 独立索引与元数据过滤
"""

from __future__ import annotations

import logging
from typing import Any

from omnievolve.storage.db import Database
from omnievolve.storage.vector_backend import VectorBackend
from omnievolve.utils.embedding import Embedder

logger = logging.getLogger(__name__)


class HybridRetriever:
    """混合检索器.

    结合全文检索（FTS5）和向量检索（Vector），
    通过 RRF (Reciprocal Rank Fusion) 融合结果。
    """

    def __init__(
        self,
        db: Database,
        vector_backend: VectorBackend,
        embedder: Embedder,
        *,
        fts_available: bool = True,
        rrf_k: int = 60,
    ) -> None:
        """初始化.

        Args:
            db: 数据库
            vector_backend: 向量后端
            embedder: 嵌入器
            fts_available: FTS5 是否可用
            rrf_k: RRF 融合参数
        """
        self._db = db
        self._vector_backend = vector_backend
        self._embedder = embedder
        self._fts_available = fts_available
        self._rrf_k = rrf_k

    def search_thoughts(
        self,
        query: str,
        *,
        experiment_id: str | None = None,
        top_k: int = 10,
    ) -> list[dict]:
        """搜索思想."""
        return self._hybrid_search(
            query=query,
            entity_type="thought",
            table="thought_record",
            content_column="content",
            experiment_id=experiment_id,
            top_k=top_k,
        )

    def search_candidates(
        self,
        query: str,
        *,
        experiment_id: str | None = None,
        top_k: int = 10,
    ) -> list[dict]:
        """搜索候选."""
        return self._hybrid_search(
            query=query,
            entity_type="candidate",
            table="candidate",
            content_column="meta",
            experiment_id=experiment_id,
            top_k=top_k,
        )

    def search_memory(
        self,
        query: str,
        *,
        experiment_id: str | None = None,
        scope_level: int | None = None,
        top_k: int = 10,
    ) -> list[dict]:
        """搜索记忆."""
        return self._hybrid_search(
            query=query,
            entity_type="memory",
            table="memory_entry",
            content_column="outcome_summary",
            experiment_id=experiment_id,
            top_k=top_k,
            extra_filters={"scope_level": scope_level} if scope_level else None,
        )

    def _hybrid_search(
        self,
        query: str,
        entity_type: str,
        table: str,
        content_column: str,
        *,
        experiment_id: str | None = None,
        top_k: int = 10,
        extra_filters: dict | None = None,
    ) -> list[dict]:
        """混合搜索.

        1. FTS5 全文检索（如果可用）
        2. Vector 向量检索
        3. RRF 融合排序
        """
        fts_results = []
        vector_results = []

        # 1. FTS5 检索
        if self._fts_available:
            fts_results = self._fts_search(query, table, content_column, experiment_id, top_k * 2)

        # 2. Vector 检索
        vector_results = self._vector_search(query, entity_type, experiment_id, top_k * 2)

        # 3. RRF 融合
        fused = self._rrf_fuse(fts_results, vector_results)

        # 4. 应用额外过滤器
        if extra_filters:
            fused = [r for r in fused if all(r.get(k) == v for k, v in extra_filters.items())]

        return fused[:top_k]

    def _fts_search(
        self,
        query: str,
        table: str,
        content_column: str,
        experiment_id: str | None,
        limit: int,
    ) -> list[dict]:
        """FTS5 全文检索."""
        results = []

        try:
            # 根据 table 选择 FTS 表
            fts_table = {
                "thought_record": "thought_fts",
                "memory_entry": "memory_fts",
            }.get(table)

            if fts_table is None:
                # 没有 FTS 索引的表，使用 LIKE
                sql = f"""
                    SELECT id, {content_column} as content
                    FROM {table}
                    WHERE {content_column} LIKE ?
                """
                params: list[Any] = [f"%{query}%"]

                if experiment_id:
                    sql += " AND experiment_id = ?"
                    params.append(experiment_id)

                sql += " LIMIT ?"
                params.append(limit)

                rows = self._db.fetchall(sql, tuple(params))
                for rank, row in enumerate(rows):
                    results.append(
                        {
                            "id": row["id"],
                            "content": row["content"],
                            "score": 1.0 / (rank + 1),  # 简单排名分数
                            "source": "fts",
                        }
                    )
            else:
                # 使用 FTS5
                sql = f"""
                    SELECT t.id, t.{content_column} as content
                    FROM {fts_table} f
                    JOIN {table} t ON f.content = t.{content_column}
                    WHERE {fts_table} MATCH ?
                """
                params = [query]

                if experiment_id:
                    sql += " AND t.experiment_id = ?"
                    params.append(experiment_id)

                sql += " LIMIT ?"
                params.append(limit)

                rows = self._db.fetchall(sql, tuple(params))
                for rank, row in enumerate(rows):
                    results.append(
                        {
                            "id": row["id"],
                            "content": row["content"],
                            "score": 1.0 / (rank + 1),
                            "source": "fts",
                        }
                    )

        except Exception as e:
            logger.debug(f"FTS search failed: {e}")

        return results

    def _vector_search(
        self,
        query: str,
        entity_type: str,
        experiment_id: str | None,
        limit: int,
    ) -> list[dict]:
        """向量检索."""
        results = []

        try:
            # 生成查询向量
            vectors = self._embedder.embed([query])
            query_vector = vectors[0]

            # 确定集合名
            collection = f"{entity_type}_default"

            # 构造过滤器
            filters = {}
            if experiment_id:
                filters["experiment_id"] = experiment_id

            hits = self._vector_backend.query(collection, query_vector, limit, filters=filters)

            for hit in hits:
                results.append(
                    {
                        "id": hit.id,
                        "score": hit.similarity,
                        "source": "vector",
                        "metadata": hit.metadata,
                    }
                )

        except Exception as e:
            logger.debug(f"Vector search failed: {e}")

        return results

    def _rrf_fuse(
        self,
        results_a: list[dict],
        results_b: list[dict],
    ) -> list[dict]:
        """RRF (Reciprocal Rank Fusion) 融合.

        RRF(d) = sum(1 / (k + rank(d)))
        """
        scores: dict[str, float] = {}
        contents: dict[str, dict] = {}

        for rank, result in enumerate(results_a):
            doc_id = result["id"]
            scores[doc_id] = scores.get(doc_id, 0) + 1.0 / (self._rrf_k + rank + 1)
            contents[doc_id] = result

        for rank, result in enumerate(results_b):
            doc_id = result["id"]
            scores[doc_id] = scores.get(doc_id, 0) + 1.0 / (self._rrf_k + rank + 1)
            if doc_id not in contents:
                contents[doc_id] = result

        # 按 RRF 分数排序
        sorted_ids = sorted(scores.items(), key=lambda x: x[1], reverse=True)

        fused = []
        for doc_id, score in sorted_ids:
            result = contents[doc_id].copy()
            result["fused_score"] = score
            fused.append(result)

        return fused

    def check_novelty(
        self,
        text: str,
        collection: str = "candidate_default",
        threshold: float = 0.92,
    ) -> tuple[bool, float]:
        """检查新颖性.

        Returns:
            (is_novel, max_similarity)
        """
        try:
            vectors = self._embedder.embed([text])
            query_vector = vectors[0]

            hits = self._vector_backend.query(collection, query_vector, top_k=1)

            if not hits:
                return True, 0.0

            max_sim = hits[0].similarity
            return max_sim < threshold, max_sim

        except Exception:
            return True, 0.0
