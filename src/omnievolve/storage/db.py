"""SQLite 连接管理、WAL 模式、事务封装.

S1-02: 建立数据库连接与 PRAGMA 策略
- WAL journal mode
- foreign_keys ON
- busy_timeout = 5000ms
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any


class Database:
    """SQLite 数据库连接管理器.

    线程安全：每个线程使用独立连接。
    WAL 模式支持并发读写。
    """

    def __init__(
        self,
        db_path: str | Path,
        *,
        wal: bool = True,
        foreign_keys: bool = True,
        busy_timeout: int = 5000,
    ) -> None:
        self._db_path = Path(db_path)
        self._wal = wal
        self._foreign_keys = foreign_keys
        self._busy_timeout = busy_timeout
        self._local = threading.local()
        self._lock = threading.Lock()

        # 确保父目录存在
        self._db_path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def db_path(self) -> Path:
        return self._db_path

    def _create_connection(self) -> sqlite3.Connection:
        """创建新连接并配置 PRAGMA."""
        conn = sqlite3.connect(
            str(self._db_path),
            check_same_thread=False,
            isolation_level=None,  # 手动管理事务
        )
        conn.row_factory = sqlite3.Row

        # 配置 PRAGMA
        if self._wal:
            conn.execute("PRAGMA journal_mode=WAL")
        if self._foreign_keys:
            conn.execute("PRAGMA foreign_keys=ON")
        conn.execute(f"PRAGMA busy_timeout={self._busy_timeout}")

        # 性能优化
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA cache_size=-64000")  # 64MB cache

        return conn

    @property
    def fts5_available(self) -> bool:
        """检测 FTS5 是否可用.

        S1-12: 配置 SQLite FTS5 能力检测与降级
        某些系统 SQLite 编译时未包含 FTS5 扩展。
        """
        conn = self.get_connection()
        try:
            conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS _fts5_probe USING fts5(content)")
            conn.execute("DROP TABLE IF EXISTS _fts5_probe")
            return True
        except Exception:
            return False

    def get_connection(self) -> sqlite3.Connection:
        """获取当前线程的连接（惰性创建）."""
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = self._create_connection()
        return self._local.conn

    @contextmanager
    def transaction(self) -> Generator[sqlite3.Connection, None, None]:
        """事务上下文管理器.

        成功时自动提交，异常时回滚。

        Usage:
            with db.transaction() as conn:
                conn.execute("INSERT ...")
        """
        conn = self.get_connection()
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise

    @contextmanager
    def read_transaction(self) -> Generator[sqlite3.Connection, None, None]:
        """只读事务上下文管理器.

        使用 BEGIN DEFERRED 允许并发读。
        """
        conn = self.get_connection()
        conn.execute("BEGIN DEFERRED")
        try:
            yield conn
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> sqlite3.Cursor:
        """执行单条 SQL（自动提交模式）."""
        conn = self.get_connection()
        return conn.execute(sql, params)

    def executemany(self, sql: str, params_seq: list[tuple[Any, ...]]) -> sqlite3.Cursor:
        """批量执行 SQL."""
        conn = self.get_connection()
        return conn.executemany(sql, params_seq)

    def fetchone(self, sql: str, params: tuple[Any, ...] = ()) -> sqlite3.Row | None:
        """查询单行."""
        cursor = self.execute(sql, params)
        return cursor.fetchone()

    def fetchall(self, sql: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
        """查询所有行."""
        cursor = self.execute(sql, params)
        return cursor.fetchall()

    def close(self) -> None:
        """关闭当前线程连接."""
        if hasattr(self._local, "conn") and self._local.conn is not None:
            self._local.conn.close()
            self._local.conn = None

    def close_all(self) -> None:
        """关闭所有连接（用于清理）."""
        self.close()

    def __enter__(self) -> Database:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()


def create_memory_database() -> Database:
    """创建内存数据库（用于测试）."""
    db = Database(":memory:")
    return db
