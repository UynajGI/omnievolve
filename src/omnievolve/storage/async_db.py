"""异步数据库包装器 — asyncio.to_thread + 写串行化.

从 ShinkaEvolve async_dbase.py 精简移植，适配 OmniEvolve 已有线程安全的 Database。
OmniEvolve 的 Database 已有 thread-local 连接 + WAL，无需 per-op 创建连接。
仅需 Semaphore(1) 串行化写操作避免 "database is locked"。
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from omnievolve.storage.db import Database


class AsyncDatabase:
    """异步数据库包装器.

    所有操作通过 asyncio.to_thread 委托到同步 Database。
    写操作用 Semaphore(1) 串行化（WAL 允许并发读但只允许一个写）。
    读操作用 Semaphore(max_reads) 限制并发数。
    """

    def __init__(
        self,
        sync_db: Database,
        *,
        max_reads: int = 8,
    ) -> None:
        self._db = sync_db
        self._read_sem = asyncio.Semaphore(max_reads)
        self._write_sem = asyncio.Semaphore(1)

    async def execute_async(
        self,
        sql: str,
        params: tuple = (),
    ) -> Any:
        """异步执行写操作（串行化）."""
        async with self._write_sem:
            return await asyncio.to_thread(self._db.execute, sql, params)

    async def fetchone_async(
        self,
        sql: str,
        params: tuple = (),
    ) -> Any:
        """异步查询单行."""
        async with self._read_sem:
            return await asyncio.to_thread(self._db.fetchone, sql, params)

    async def fetchall_async(
        self,
        sql: str,
        params: tuple = (),
    ) -> list[Any]:
        """异步查询多行."""
        async with self._read_sem:
            return await asyncio.to_thread(self._db.fetchall, sql, params)

    @asynccontextmanager
    async def transaction_async(self):
        """异步事务上下文管理器.

        写操作自动串行化。在上下文内使用 execute_async 写操作会被同一个
        写信号量保护，但 BEGIN/COMMIT/ROLLBACK 由本方法管理。
        """
        async with self._write_sem:
            # 获取连接并启动事务
            conn = await asyncio.to_thread(self._db.get_connection)
            try:
                await asyncio.to_thread(conn.execute, "BEGIN IMMEDIATE")
                yield self
                await asyncio.to_thread(conn.execute, "COMMIT")
            except Exception:
                try:
                    await asyncio.to_thread(conn.execute, "ROLLBACK")
                except Exception:
                    pass  # ROLLBACK 失败不影响原始异常传播
                raise

    async def read_op(self, func: Any, *args: Any, **kwargs: Any) -> Any:
        """在线程池中执行读操作."""
        async with self._read_sem:
            return await asyncio.to_thread(func, *args, **kwargs)

    async def write_op(self, func: Any, *args: Any, **kwargs: Any) -> Any:
        """在写线程中执行写操作（串行化）."""
        async with self._write_sem:
            return await asyncio.to_thread(func, *args, **kwargs)

    @property
    def sync_db(self) -> Database:
        """Escape hatch — 直接访问同步 DB."""
        return self._db

    def __getattr__(self, name: str) -> Any:
        """委托未知属性到同步 DB（close/db_path/fts5_available 等）."""
        return getattr(self._db, name)
