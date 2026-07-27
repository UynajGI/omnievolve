"""zvec 向量后端 Adapter.

S6-07: 实现 zvec Adapter 与 collection lifecycle

zvec 是嵌入式 ANN 库（HNSW/IVF/Flat），此文件封装其 API。
如果 zvec 未安装，回退到 NumpyBackend。

zvec 0.6 API:
  - zvec.create_and_open(path, schema) -> Collection
  - zvec.open(path) -> Collection
  - Collection.upsert([Doc(id=..., vectors={'embedding': [...]})])
  - Collection.query(queries=Query(field_name='embedding', vector=[...]), topk=N) -> DocList
  - Collection.delete(ids=[...])
"""

from __future__ import annotations

import atexit
import logging
import shutil
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from omnievolve.storage.numpy_backend import NumpyVectorBackend
from omnievolve.storage.vector_backend import VectorHit, VectorRecord

logger = logging.getLogger(__name__)

_VECTOR_FIELD = "embedding"  # zvec 向量字段名


class ZvecBackend:
    """zvec 向量后端.

    封装 zvec 0.6 的 Collection API。
    当 zvec 不可用时自动回退到 NumpyBackend。
    """

    def __init__(
        self,
        storage_path: str | None = None,
        *,
        metric: str = "cosine",
        m: int = 16,
        ef_construction: int = 200,
    ) -> None:
        """初始化 zvec 后端.

        Args:
            storage_path: 集合存储根目录（默认临时目录）
            metric: 距离度量 (cosine/l2/ip)
            m: HNSW 双向链接数
            ef_construction: HNSW 构建时候选列表大小
        """
        self._storage_path = storage_path or tempfile.mkdtemp(prefix="omnievolve_zvec_")
        self._owns_storage = storage_path is None  # 标记是否为自建临时目录
        self._metric = metric
        self._m = m
        self._ef_construction = ef_construction
        self._zvec: Any = None
        self._collections: dict[str, Any] = {}  # name -> zvec.Collection
        self._dimensions: dict[str, int] = {}  # name -> dimension
        self._metadata: dict[str, dict[str, dict]] = {}  # name -> {id -> metadata}
        self._fallback = NumpyVectorBackend()

        # 尝试导入 zvec
        try:
            import zvec  # type: ignore

            self._zvec = zvec
            Path(self._storage_path).mkdir(parents=True, exist_ok=True)
            logger.info("zvec backend initialized (storage: %s)", self._storage_path)
        except ImportError:
            logger.warning(
                "zvec not installed, falling back to NumPy backend. "
                "Install with: pip install omnievolve[vector]"
            )

        # 进程退出时自动清理临时目录
        if self._owns_storage:
            atexit.register(self.cleanup)

    def _metric_type(self) -> Any:
        """获取 zvec MetricType."""
        mapping = {
            "cosine": self._zvec.MetricType.COSINE,
            "l2": self._zvec.MetricType.L2,
            "ip": self._zvec.MetricType.IP,
        }
        return mapping.get(self._metric, self._zvec.MetricType.COSINE)

    def create_or_open(self, collection: str, dimension: int) -> None:
        """创建或打开集合."""
        if self._zvec is None:
            self._fallback.create_or_open(collection, dimension)
            return

        if collection in self._collections:
            return

        coll_path = str(Path(self._storage_path) / collection)

        # 尝试打开已有集合
        try:
            coll = self._zvec.open(coll_path)
            self._collections[collection] = coll
            self._dimensions[collection] = dimension
            self._metadata.setdefault(collection, {})
            logger.debug("Opened existing zvec collection: %s", collection)
            return
        except Exception:
            pass  # 不存在，创建新的

        # 创建新集合
        try:
            schema = self._zvec.CollectionSchema(
                name=collection,
                vectors=[
                    self._zvec.VectorSchema(
                        name=_VECTOR_FIELD,
                        data_type=self._zvec.DataType.VECTOR_FP32,
                        dimension=dimension,
                        index_param=self._zvec.HnswIndexParam(
                            metric_type=self._metric_type(),
                            m=self._m,
                            ef_construction=self._ef_construction,
                        ),
                    )
                ],
            )
            coll = self._zvec.create_and_open(coll_path, schema)
            self._collections[collection] = coll
            self._dimensions[collection] = dimension
            self._metadata.setdefault(collection, {})
            logger.info(
                "Created zvec collection: %s (dim=%d, HNSW m=%d)", collection, dimension, self._m
            )
        except Exception as e:
            logger.warning("Failed to create zvec collection: %s, using NumPy fallback", e)
            self._fallback.create_or_open(collection, dimension)

    def upsert(self, collection: str, records: list[VectorRecord]) -> None:
        """插入或更新向量."""
        if self._zvec is None or collection not in self._collections:
            self._fallback.upsert(collection, records)
            return

        coll = self._collections[collection]
        docs = [
            self._zvec.Doc(
                id=record.id,
                vectors={_VECTOR_FIELD: list(record.vector)},
            )
            for record in records
        ]

        try:
            coll.upsert(docs)
            # 保存 metadata（zvec Doc.fields 可选，这里用内存 dict 维护）
            meta_store = self._metadata.setdefault(collection, {})
            for record in records:
                if record.metadata:
                    meta_store[record.id] = record.metadata
        except Exception as e:
            logger.warning("zvec upsert failed: %s, falling back", e)
            self._fallback.upsert(collection, records)

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

        try:
            q = self._zvec.Query(field_name=_VECTOR_FIELD, vector=list(vector))
            # 多取一些以便过滤后仍有足够结果
            fetch_k = top_k * 3 if filters else top_k
            results = coll.query(queries=q, topk=fetch_k)

            hits = []
            meta_store = self._metadata.get(collection, {})

            for doc in results:
                metadata = meta_store.get(doc.id, {})

                # 应用过滤器
                if filters:
                    if not all(metadata.get(k) == v for k, v in filters.items()):
                        continue

                # zvec COSINE 返回距离 (0=相同)，转换为相似度 (1=相同)
                raw_score = float(doc.score) if doc.score is not None else 0.0
                if self._metric == "cosine":
                    similarity = 1.0 - raw_score
                else:
                    similarity = raw_score

                hits.append(
                    VectorHit(
                        id=doc.id,
                        similarity=similarity,
                        metadata=metadata,
                    )
                )

                if len(hits) >= top_k:
                    break

            return hits
        except Exception as e:
            logger.warning("zvec query failed: %s, falling back", e)
            return self._fallback.query(collection, vector, top_k, filters)

    def delete(self, collection: str, ids: list[str]) -> None:
        """删除向量."""
        if self._zvec is None or collection not in self._collections:
            self._fallback.delete(collection, ids)
            return

        coll = self._collections[collection]
        try:
            coll.delete(ids=ids)
            meta_store = self._metadata.get(collection, {})
            for doc_id in ids:
                meta_store.pop(doc_id, None)
        except Exception as e:
            logger.warning("zvec delete failed: %s", e)
            self._fallback.delete(collection, ids)

    def healthcheck(self, collection: str) -> dict:
        """健康检查."""
        if self._zvec is None:
            return self._fallback.healthcheck(collection)

        count = len(self._metadata.get(collection, {}))
        return {
            "status": "healthy",
            "backend": "zvec",
            "collection": collection,
            "count": count,
            "index_type": "hnsw",
            "metric": self._metric,
            "storage_path": self._storage_path,
        }

    def is_using_fallback(self) -> bool:
        """是否使用 NumPy fallback."""
        return self._zvec is None

    def cleanup(self) -> None:
        """清理自建临时目录."""
        if self._owns_storage:
            try:
                shutil.rmtree(self._storage_path, ignore_errors=True)
            except Exception:
                logger.debug("Failed to clean up zvec storage: %s", self._storage_path)


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
