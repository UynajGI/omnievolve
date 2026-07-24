"""Unit of Work 事务封装.

S1-08: 实现 Unit of Work / 事务封装
- 一个业务操作只在单一事务边界提交
- 异常不会半写
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Generator
from contextlib import contextmanager
from typing import Any, TypeVar

from omnievolve.storage.db import Database

logger = logging.getLogger(__name__)

T = TypeVar("T")


class UnitOfWork:
    """Unit of Work 模式封装.

    确保业务操作在单一事务边界内完成。
    支持嵌套（使用 savepoint）。

    Usage:
        uow = UnitOfWork(db)
        with uow:
            uow.connection.execute("INSERT ...")
            uow.connection.execute("UPDATE ...")
        # 自动提交

        # 或者显式控制
        uow.begin()
        try:
            uow.connection.execute("INSERT ...")
            uow.commit()
        except Exception:
            uow.rollback()
            raise
    """

    def __init__(self, db: Database) -> None:
        self._db = db
        self._in_transaction = False
        self._savepoint_counter = 0

    @property
    def connection(self):
        """获取数据库连接."""
        return self._db.get_connection()

    @property
    def in_transaction(self) -> bool:
        return self._in_transaction

    def begin(self) -> None:
        """开始事务."""
        if self._in_transaction:
            # 嵌套事务使用 savepoint
            self._savepoint_counter += 1
            self.connection.execute(f"SAVEPOINT sp_{self._savepoint_counter}")
        else:
            self.connection.execute("BEGIN IMMEDIATE")
            self._in_transaction = True

    def commit(self) -> None:
        """提交事务."""
        if self._savepoint_counter > 0:
            self.connection.execute(f"RELEASE SAVEPOINT sp_{self._savepoint_counter}")
            self._savepoint_counter -= 1
        else:
            self.connection.execute("COMMIT")
            self._in_transaction = False

    def rollback(self) -> None:
        """回滚事务."""
        if self._savepoint_counter > 0:
            self.connection.execute(f"ROLLBACK TO SAVEPOINT sp_{self._savepoint_counter}")
            self._savepoint_counter -= 1
        else:
            self.connection.execute("ROLLBACK")
            self._in_transaction = False

    def __enter__(self) -> UnitOfWork:
        self.begin()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if exc_type is not None:
            self.rollback()
        else:
            self.commit()


def transactional(db: Database) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """事务装饰器.

    被装饰的函数将在单一事务中执行。

    Usage:
        @transactional(db)
        def create_candidate(conn, data):
            conn.execute("INSERT ...")
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        def wrapper(*args: Any, **kwargs: Any) -> T:
            uow = UnitOfWork(db)
            with uow:
                return func(uow.connection, *args, **kwargs)

        return wrapper

    return decorator


@contextmanager
def atomic(db: Database) -> Generator[Any, None, None]:
    """原子操作上下文管理器.

    Usage:
        with atomic(db) as conn:
            conn.execute("INSERT ...")
    """
    uow = UnitOfWork(db)
    uow.begin()
    try:
        yield uow.connection
        uow.commit()
    except Exception:
        uow.rollback()
        raise
