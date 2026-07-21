"""VectorBackend Protocol.

S6-05: 冻结 VectorBackend Protocol
设计文档 4.2 节：所有向量后端通过统一接口接入，以 profile_id 标识集合。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class VectorRecord:
    """向量记录."""

    id: str
    vector: Sequence[float]
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class VectorHit:
    """向量检索结果."""

    id: str
    similarity: float
    metadata: dict = field(default_factory=dict)


@runtime_checkable
class VectorBackend(Protocol):
    """向量后端 Protocol.

    设计文档要求以 profile_id 标识集合（对应 EmbeddingProfile.id），
    而非模糊的 collection 名称。
    """

    def create_or_open(self, profile_id: str, dimension: int) -> None:
        """创建或打开集合."""
        ...

    def upsert(self, profile_id: str, records: list[VectorRecord]) -> None:
        """插入或更新向量."""
        ...

    def query(
        self,
        profile_id: str,
        vector: Sequence[float],
        top_k: int,
        filters: dict | None = None,
    ) -> list[VectorHit]:
        """查询相似向量."""
        ...

    def delete(self, profile_id: str, ids: list[str]) -> None:
        """删除向量."""
        ...

    def healthcheck(self, profile_id: str) -> dict:
        """健康检查."""
        ...
