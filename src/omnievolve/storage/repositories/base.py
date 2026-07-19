"""Repository 基础协议.

S1-09: 实现 Repository 基础协议
- CRUD 与查询不泄漏 sqlite3 细节
- 可用内存库测试
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any, Generic, Protocol, TypeVar, runtime_checkable

from omnievolve.storage.db import Database

T = TypeVar("T")


def generate_id() -> str:
    """生成唯一 ID."""
    return uuid.uuid4().hex[:16]


def now_iso() -> str:
    """当前时间 ISO 格式."""
    return datetime.now(UTC).isoformat()


@runtime_checkable
class Repository(Protocol[T]):
    """Repository 基础协议.

    所有 Repository 实现此协议，确保：
    - CRUD 操作不泄漏 sqlite3 细节
    - 返回领域对象而非 Row
    - 支持事务
    """

    def get(self, entity_id: str) -> T | None:
        """根据 ID 获取实体."""
        ...

    def list(
        self,
        limit: int = 100,
        offset: int = 0,
        **filters: Any,
    ) -> list[T]:
        """列出实体."""
        ...

    def create(self, entity: T) -> str:
        """创建实体，返回 ID."""
        ...

    def update(self, entity_id: str, **updates: Any) -> bool:
        """更新实体."""
        ...

    def delete(self, entity_id: str) -> bool:
        """删除实体."""
        ...


class BaseRepository(Generic[T]):
    """Repository 基础实现.

    提供通用的 CRUD 操作，子类只需定义：
    - table_name: 表名
    - _row_to_entity: Row 转领域对象
    - _entity_to_dict: 领域对象转 dict
    """

    table_name: str = ""

    def __init__(self, db: Database) -> None:
        self._db = db

    def _row_to_entity(self, row: Any) -> T:
        """将数据库 Row 转换为领域对象. 子类必须实现."""
        raise NotImplementedError

    def _entity_to_dict(self, entity: T) -> dict[str, Any]:
        """将领域对象转换为 dict. 子类必须实现."""
        raise NotImplementedError

    def get(self, entity_id: str) -> T | None:
        """根据 ID 获取实体."""
        row = self._db.fetchone(
            f"SELECT * FROM {self.table_name} WHERE id = ?",
            (entity_id,),
        )
        if row is None:
            return None
        return self._row_to_entity(row)

    def list(
        self,
        limit: int = 100,
        offset: int = 0,
        order_by: str = "created_at DESC",
        **filters: Any,
    ) -> list[T]:
        """列出实体."""
        where_clauses = []
        params = []

        for key, value in filters.items():
            if value is not None:
                where_clauses.append(f"{key} = ?")
                params.append(value)

        where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"
        sql = f"SELECT * FROM {self.table_name} WHERE {where_sql} ORDER BY {order_by} LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        rows = self._db.fetchall(sql, tuple(params))
        return [self._row_to_entity(row) for row in rows]

    def create(self, entity: T) -> str:
        """创建实体."""
        data = self._entity_to_dict(entity)
        entity_id = data.get("id") or generate_id()
        data["id"] = entity_id

        columns = ", ".join(data.keys())
        placeholders = ", ".join(["?"] * len(data))
        values = tuple(data.values())

        self._db.execute(
            f"INSERT INTO {self.table_name} ({columns}) VALUES ({placeholders})",
            values,
        )
        return entity_id

    def update(self, entity_id: str, **updates: Any) -> bool:
        """更新实体."""
        if not updates:
            return False

        # 处理 JSON 字段
        processed = {}
        for key, value in updates.items():
            if isinstance(value, (dict, list)):
                processed[key] = json.dumps(value, ensure_ascii=False)
            else:
                processed[key] = value

        set_clause = ", ".join(f"{k} = ?" for k in processed.keys())
        values = tuple(processed.values()) + (entity_id,)

        cursor = self._db.execute(
            f"UPDATE {self.table_name} SET {set_clause} WHERE id = ?",
            values,
        )
        return cursor.rowcount > 0

    def delete(self, entity_id: str) -> bool:
        """删除实体."""
        cursor = self._db.execute(
            f"DELETE FROM {self.table_name} WHERE id = ?",
            (entity_id,),
        )
        return cursor.rowcount > 0

    def count(self, **filters: Any) -> int:
        """计数."""
        where_clauses = []
        params = []

        for key, value in filters.items():
            if value is not None:
                where_clauses.append(f"{key} = ?")
                params.append(value)

        where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"
        row = self._db.fetchone(
            f"SELECT COUNT(*) as cnt FROM {self.table_name} WHERE {where_sql}",
            tuple(params),
        )
        return row["cnt"] if row else 0

    def exists(self, entity_id: str) -> bool:
        """检查实体是否存在."""
        row = self._db.fetchone(
            f"SELECT 1 FROM {self.table_name} WHERE id = ?",
            (entity_id,),
        )
        return row is not None
