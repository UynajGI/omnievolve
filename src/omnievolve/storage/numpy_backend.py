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
        """精确 KNN 查询."""
        if collection not in self._collections:
            return []

        items = self._collections[collection]
        if not items:
            return []

        query_vec = np.array(vector, dtype=np.float32)

        # 计算余弦相似度
        hits = []
        for id, (vec, metadata) in items.items():
            # 应用过滤器
            if filters:
                if not all(metadata.get(k) == v for k, v in filters.items()):
                    continue

            # 余弦相似度
            norm_query = np.linalg.norm(query_vec)
            norm_vec = np.linalg.norm(vec)
            if norm_query > 0 and norm_vec > 0:
                similarity = float(np.dot(query_vec, vec) / (norm_query * norm_vec))
            else:
                similarity = 0.0

            hits.append(VectorHit(id=id, similarity=similarity, metadata=metadata))

        # 排序并返回 top_k
        hits.sort(key=lambda x: x.similarity, reverse=True)
        return hits[:top_k]

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
