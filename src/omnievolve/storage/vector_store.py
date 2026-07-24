"""混合检索器 - FTS5 + Vector + scope filter + rerank.

S6-11: 实现 FTS5 文档与作用域索引
S6-12: 实现 Hybrid Retriever 与融合排序
S6-13: 实现 code/thought 独立索引与元数据过滤

设计文档 §8: VectorStore 上层 Facade
- semantic_candidates: 语义检索候选
- find_diverse_high_scorers: 多样化高分候选
- rag_retrieve: FTS5 + Vector + scope filter + rerank
"""

from __future__ import annotations

import logging
from typing import Any

from omnievolve.storage.db import Database
from omnievolve.storage.vector_backend import VectorBackend, VectorHit
from omnievolve.utils.embedding import Embedder

logger = logging.getLogger(__name__)


class VectorStore:
    """设计文档 §8: 向量存储上层 Facade.

    封装 VectorBackend + Embedder，提供语义检索、多样化采样和 RAG 检索。
    """

    def __init__(
        self,
        backend: VectorBackend,
        embedder: Embedder,
        db: Database | None = None,
    ) -> None:
        self._backend = backend
        self._embedder = embedder
        self._db = db

    def semantic_candidates(
        self,
        text: str,
        purpose: str = "inspiration",
        scope: dict | None = None,
        top_k: int = 10,
    ) -> list[VectorHit]:
        """语义检索候选.

        Args:
            text: 查询文本（thought / 代码片段）
            purpose: 检索目的 (inspiration / novelty / repair)
            scope: 作用域过滤 (experiment_id, island_id, ...)
            top_k: 返回数量
        """
        try:
            vectors = self._embedder.embed([text])
            query_vector = vectors[0]

            # 根据 purpose 选择集合
            collection = "candidate_default"
            filters = dict(scope) if scope else None

            return self._backend.query(collection, query_vector, top_k, filters=filters)
        except Exception as e:
            logger.debug("semantic_candidates failed: %s", e)
            return []

    def find_diverse_high_scorers(
        self,
        experiment_id: str,
        exclude_ids: list[str] | None = None,
        top_k: int = 3,
    ) -> list[str]:
        """查找多样化高分候选（向量距离贪心）.

        从 DB 取 top-N 高分候选，然后用向量距离贪心选择最大化多样性的子集。
        """
        if self._db is None:
            return []

        exclude_ids = exclude_ids or []

        # 从 DB 获取高分候选
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
            (experiment_id, top_k * 5),
        )

        candidates = [r["id"] for r in rows if r["id"] not in exclude_ids]
        if len(candidates) <= top_k:
            return candidates

        # 向量距离贪心多样化
        try:
            vectors = self._embedder.embed(candidates[:top_k * 3])
            selected_indices = [0]  # 从最高分开始

            while len(selected_indices) < top_k and len(selected_indices) < len(vectors):
                best_idx = -1
                best_min_dist = -1.0

                for i in range(len(vectors)):
                    if i in selected_indices:
                        continue
                    # 计算与已选集合的最小距离
                    min_dist = min(
                        1.0 - self._cosine_sim(vectors[i], vectors[j])
                        for j in selected_indices
                    )
                    if min_dist > best_min_dist:
                        best_min_dist = min_dist
                        best_idx = i

                if best_idx >= 0:
                    selected_indices.append(best_idx)
                else:
                    break

            return [candidates[i] for i in selected_indices]
        except Exception as e:
            logger.debug("find_diverse_high_scorers vector diversity failed: %s", e)
            return candidates[:top_k]

    def rag_retrieve(
        self,
        query: str,
        scope_weights: dict[str, float] | None = None,
        top_k: int = 5,
    ) -> list[dict]:
        """FTS5 + Vector + scope filter + rerank.

        Args:
            query: 检索查询
            scope_weights: 作用域权重 {"experiment": 1.0, "island": 0.5, ...}
            top_k: 返回数量
        """
        results: list[dict] = []

        # Vector 检索
        try:
            vectors = self._embedder.embed([query])
            query_vector = vectors[0]

            # 检索 thought 和 candidate 两个集合
            for collection in ("thought_default", "candidate_default"):
                hits = self._backend.query(collection, query_vector, top_k * 2)
                for hit in hits:
                    weight = 1.0
                    if scope_weights and hit.metadata.get("scope"):
                        weight = scope_weights.get(hit.metadata["scope"], 0.5)
                    results.append({
                        "id": hit.id,
                        "score": hit.similarity * weight,
                        "source": "vector",
                        "collection": collection,
                        "metadata": hit.metadata,
                    })
        except Exception as e:
            logger.debug("rag_retrieve vector search failed: %s", e)

        # FTS5 检索（如果有 DB）
        if self._db is not None:
            try:
                fts_rows = self._db.fetchall(
                    """
                    SELECT entity_id, rank
                    FROM thought_fts
                    WHERE thought_fts MATCH ?
                    LIMIT ?
                    """,
                    (query, top_k * 2),
                )
                for row in fts_rows:
                    results.append({
                        "id": row["entity_id"],
                        "score": 1.0 / (abs(row["rank"]) + 1),
                        "source": "fts",
                        "collection": "thought_default",
                    })
            except Exception as e:
                logger.debug("rag_retrieve FTS failed: %s", e)

        # 按分数排序去重
        seen: set[str] = set()
        deduped: list[dict] = []
        for r in sorted(results, key=lambda x: x["score"], reverse=True):
            if r["id"] not in seen:
                seen.add(r["id"])
                deduped.append(r)

        return deduped[:top_k]

    def check_novelty(
        self,
        text: str,
        collection: str = "candidate_default",
        threshold: float = 0.92,
    ) -> tuple[bool, float]:
        """检查文本新颖性（委托到底层 backend 查询）.

        Returns:
            (is_novel, max_similarity)
        """
        try:
            vectors = self._embedder.embed([text])
            hits = self._backend.query(collection, vectors[0], top_k=1)
            if not hits:
                return True, 0.0
            max_sim = hits[0].similarity
            return max_sim < threshold, max_sim
        except Exception as e:
            logger.warning("Novelty check failed, defaulting to novel: %s", e)
            return True, 0.0

    def query_parallel_profiles(
        self,
        text: str,
        collections: list[str],
        top_k: int = 10,
    ) -> list[dict[str, Any]]:
        """设计文档 §8.2: 新旧 Profile 并行查询.

        Embedding 模型更换时，新旧索引并行查询，
        合并结果后按相似度排序。达到覆盖率后再切换默认 Profile。

        Args:
            text: 查询文本
            collections: 多个 collection 名称（如 ["candidate_old_profile", "candidate_new_profile"]）
            top_k: 每个 collection 返回的最大结果数

        Returns:
            合并后的结果列表，按相似度降序
        """
        try:
            vectors = self._embedder.embed([text])
            query_vec = vectors[0]
        except Exception as e:
            logger.warning("Embedding failed for parallel query: %s", e)
            return []

        all_hits: list[dict[str, Any]] = []
        for collection in collections:
            try:
                hits = self._backend.query(collection, query_vec, top_k=top_k)
                for h in hits:
                    all_hits.append({
                        "id": h.id,
                        "score": h.similarity,
                        "collection": collection,
                        "metadata": h.metadata,
                    })
            except Exception as e:
                logger.debug("Parallel query failed for %s: %s", collection, e)

        # 去重 + 按相似度排序
        seen: set[str] = set()
        deduped: list[dict[str, Any]] = []
        for h in sorted(all_hits, key=lambda x: x["score"], reverse=True):
            if h["id"] not in seen:
                seen.add(h["id"])
                deduped.append(h)

        return deduped[:top_k]

    @staticmethod
    def _cosine_sim(a: list[float] | Any, b: list[float] | Any) -> float:
        """Cosine similarity."""
        import numpy as np

        va, vb = np.asarray(a), np.asarray(b)
        norm = np.linalg.norm(va) * np.linalg.norm(vb)
        if norm == 0:
            return 0.0
        return float(np.dot(va, vb) / norm)


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
                # 使用 FTS5 — entity_id JOIN 原表
                sql = f"""
                    SELECT t.id, t.{content_column} as content
                    FROM {fts_table} f
                    JOIN {table} t ON f.entity_id = t.id
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

        except Exception as e:
            logger.warning("Novelty check failed, defaulting to novel: %s", e)
            return True, 0.0
