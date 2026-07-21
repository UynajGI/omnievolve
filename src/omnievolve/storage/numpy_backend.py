"""NumPy 精确检索 Backend.

S6-06: 实现 NumPy 精确检索 fallback
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

import numpy as np

from omnievolve.storage.vector_backend import VectorHit, VectorRecord

logger = logging.getLogger(__name__)


class NumpyVectorBackend:
    """NumPy 精确检索后端.

    适用于小规模数据或 zvec 不可用时的 fallback。
    """

    def __init__(self) -> None:
        self._collections: dict[str, dict[str, tuple[np.ndarray, dict]]] = {}

    def create_or_open(self, collection: str, dimension: int) -> None:
        """创建或打开集合."""
        if collection not in self._collections:
            self._collections[collection] = {}
            logger.info(f"Created NumPy vector collection: {collection}")

    def upsert(self, collection: str, records: list[VectorRecord]) -> None:
        """插入或更新向量."""
        if collection not in self._collections:
            self.create_or_open(collection, len(records[0].vector) if records else 128)

        for record in records:
            self._collections[collection][record.id] = (
                np.array(record.vector, dtype=np.float32),
                record.metadata,
            )

    def query(
        self,
        collection: str,
        vector: Sequence[float],
        top_k: int,
        filters: dict | None = None,
    ) -> list[VectorHit]:
        """精确 KNN 查询（矩阵向量化优化）.

        P2: 使用 np.stack + 单次 dot product 代替逐条循环。
        """
        if collection not in self._collections:
            return []

        items = self._collections[collection]
        if not items:
            return []

        query_vec = np.array(vector, dtype=np.float32)
        norm_query = np.linalg.norm(query_vec)

        # 分离 ID、向量、元数据
        ids = list(items.keys())
        matrices = []
        metadatas = []
        for id_ in ids:
            vec, meta = items[id_]
            matrices.append(vec)
            metadatas.append(meta)

        # 堆叠为矩阵 [n, dim]
        matrix = np.stack(matrices)  # [n, dim]

        # 预过滤：应用 filters
        keep_mask: list[bool] = []
        if filters:
            keep_mask = [all(meta.get(k) == v for k, v in filters.items()) for meta in metadatas]
            if not any(keep_mask):
                return []
            # 应用 mask
            keep_idx = [i for i, k in enumerate(keep_mask) if k]
            matrix = matrix[keep_idx]
            ids = [ids[i] for i in keep_idx]
            metadatas = [metadatas[i] for i in keep_idx]

        # 批量余弦相似度 — 单次矩阵乘法代替 N 次循环
        if norm_query > 0:
            norms = np.linalg.norm(matrix, axis=1)  # [n]
            # 避免除零
            valid = norms > 0
            sims = np.zeros(matrix.shape[0], dtype=np.float32)
            if valid.any():
                dots = matrix[valid] @ query_vec  # [n_valid]
                sims[valid] = dots / (norms[valid] * norm_query)
        else:
            sims = np.zeros(matrix.shape[0], dtype=np.float32)

        # 排序并返回 top_k
        top_indices = np.argsort(sims)[::-1][:top_k]
        hits = [
            VectorHit(
                id=ids[i],
                similarity=float(sims[i]),
                metadata=metadatas[i],
            )
            for i in top_indices
        ]
        return hits

    def delete(self, collection: str, ids: list[str]) -> None:
        """删除向量."""
        if collection in self._collections:
            for id in ids:
                self._collections[collection].pop(id, None)

    def healthcheck(self, collection: str) -> dict:
        """健康检查."""
        count = len(self._collections.get(collection, {}))
        return {
            "status": "healthy",
            "backend": "numpy",
            "collection": collection,
            "count": count,
        }

    def count(self, collection: str) -> int:
        """获取集合大小."""
        return len(self._collections.get(collection, {}))
