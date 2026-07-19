"""zvec 向量后端 Adapter.

S6-07: 实现 zvec Adapter 与 collection lifecycle

zvec 是嵌入式 ANN 库，此文件封装其 API。
如果 zvec 未安装，回退到 NumpyBackend。
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

from omnievolve.storage.numpy_backend import NumpyVectorBackend
from omnievolve.storage.vector_backend import VectorHit, VectorRecord

logger = logging.getLogger(__name__)


class ZvecBackend:
    """zvec 向量后端.

    封装 zvec 的初始化、upsert、query、delete 等 API。
    当 zvec 不可用时自动回退到 NumpyBackend。
    """

    def __init__(
        self,
        storage_path: str | None = None,
        *,
        index_type: str = "hnsw",  # hnsw / ivf / flat
        metric: str = "cosine",
    ) -> None:
        """初始化 zvec 后端.

        Args:
            storage_path: 存储路径
            index_type: 索引类型 (hnsw/ivf/flat)
            metric: 距离度量 (cosine/l2/ip)
        """
        self._storage_path = storage_path
        self._index_type = index_type
        self._metric = metric
        self._zvec = None
        self._collections: dict[str, Any] = {}
        self._fallback = NumpyVectorBackend()

        # 尝试导入 zvec
        try:
            import zvec  # type: ignore

            self._zvec = zvec
            logger.info("zvec backend initialized")
        except ImportError:
            logger.warning(
                "zvec not installed, falling back to NumPy backend. "
                "Install with: pip install omnievolve[vector]"
            )

    def create_or_open(self, collection: str, dimension: int) -> None:
        """创建或打开集合."""
        if self._zvec is None:
            self._fallback.create_or_open(collection, dimension)
            return

        if collection not in self._collections:
            # 创建 zvec 索引
            # 实际 API 取决于 zvec 版本
            try:
                # 尝试 zvec 的标准 API
                index = self._zvec.Index(
                    dim=dimension,
                    index_type=self._index_type,
                    metric=self._metric,
                    storage_path=f"{self._storage_path}/{collection}"
                    if self._storage_path
                    else None,
                )
                self._collections[collection] = {
                    "index": index,
                    "dimension": dimension,
                    "metadata": {},  # id -> metadata 映射
                }
                logger.info(f"Created zvec collection: {collection} (dim={dimension})")
            except Exception as e:
                logger.warning(f"Failed to create zvec index: {e}, using NumPy fallback")
                self._fallback.create_or_open(collection, dimension)

    def upsert(self, collection: str, records: list[VectorRecord]) -> None:
        """插入或更新向量."""
        if self._zvec is None or collection not in self._collections:
            self._fallback.upsert(collection, records)
            return

        coll = self._collections[collection]
        for record in records:
            coll["index"].add(
                ids=[record.id],
                vectors=[list(record.vector)],
            )
            coll["metadata"][record.id] = record.metadata

    def query(
        self,
        collection: str,
        vector: Sequence[float],
        top_k: int,
        filters: dict | None = None,
    ) -> list[VectorHit]:
        """查询相似向量."""
        if self._zvec is None or collection not in self._collections:
            return self._fallback.query(collection, vector, top_k, filters)

        coll = self._collections[collection]
        results = coll["index"].search(
            query_vector=list(vector),
            k=top_k,
        )

        hits = []
        for id, similarity in results:
            metadata = coll["metadata"].get(id, {})

            # 应用过滤器
            if filters:
                if not all(metadata.get(k) == v for k, v in filters.items()):
                    continue

            hits.append(VectorHit(id=id, similarity=float(similarity), metadata=metadata))

        return hits

    def delete(self, collection: str, ids: list[str]) -> None:
        """删除向量."""
        if self._zvec is None or collection not in self._collections:
            self._fallback.delete(collection, ids)
            return

        coll = self._collections[collection]
        coll["index"].delete(ids=ids)
        for id in ids:
            coll["metadata"].pop(id, None)

    def healthcheck(self, collection: str) -> dict:
        """健康检查."""
        if self._zvec is None:
            return self._fallback.healthcheck(collection)

        count = len(self._collections.get(collection, {}).get("metadata", {}))
        return {
            "status": "healthy",
            "backend": "zvec",
            "collection": collection,
            "count": count,
            "index_type": self._index_type,
            "metric": self._metric,
        }

    def is_using_fallback(self) -> bool:
        """是否使用 NumPy fallback."""
        return self._zvec is None


def create_vector_backend(
    *,
    prefer_zvec: bool = True,
    storage_path: str | None = None,
) -> ZvecBackend | NumpyVectorBackend:
    """创建向量后端.

    优先使用 zvec，不可用时回退到 NumPy。
    """
    if prefer_zvec:
        backend = ZvecBackend(storage_path=storage_path)
        if not backend.is_using_fallback():
            return backend
        logger.info("Using NumPy fallback for vector backend")

    return NumpyVectorBackend()
