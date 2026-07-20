"""WAL 并发与锁竞争测试.

S1-14: 实现 WAL 并发与锁竞争测试
- 多读单写稳定
- busy timeout 和重试符合配置
"""

import threading
import time
from pathlib import Path

import pytest

from omnievolve.storage.db import Database
from omnievolve.storage.migrations import initialize_database
from omnievolve.storage.uow import UnitOfWork, atomic

pytestmark = pytest.mark.integration


@pytest.fixture
def db_path(tmp_path: Path):
    """数据库文件路径."""
    return tmp_path / "test.db"


@pytest.fixture
def db(db_path):
    """创建文件数据库."""
    database = Database(db_path)
    initialize_database(database)
    yield database
    database.close()


class TestWALMode:
    """WAL 模式测试."""

    def test_wal_enabled(self, db: Database):
        """WAL 模式应启用."""
        row = db.fetchone("PRAGMA journal_mode")
        assert row[0] == "wal"

    def test_foreign_keys_enabled(self, db: Database):
        """外键约束应启用."""
        row = db.fetchone("PRAGMA foreign_keys")
        assert row[0] == 1

    def test_busy_timeout_set(self, db: Database):
        """busy_timeout 应设置."""
        row = db.fetchone("PRAGMA busy_timeout")
        assert row[0] == 5000


class TestTransactions:
    """事务测试."""

    def test_transaction_commit(self, db: Database):
        """事务提交."""
        with db.transaction() as conn:
            conn.execute(
                "INSERT INTO experiment (id, task_id, task_name, config_snapshot) VALUES (?, ?, ?, ?)",
                ("exp1", "task1", "Test", "{}"),
            )

        row = db.fetchone("SELECT * FROM experiment WHERE id = ?", ("exp1",))
        assert row is not None

    def test_transaction_rollback(self, db: Database):
        """事务回滚."""
        try:
            with db.transaction() as conn:
                conn.execute(
                    "INSERT INTO experiment (id, task_id, task_name, config_snapshot) VALUES (?, ?, ?, ?)",
                    ("exp2", "task1", "Test", "{}"),
                )
                raise ValueError("Simulated error")
        except ValueError:
            pass

        row = db.fetchone("SELECT * FROM experiment WHERE id = ?", ("exp2",))
        assert row is None

    def test_uow_commit(self, db: Database):
        """UnitOfWork 提交."""
        uow = UnitOfWork(db)
        with uow:
            uow.connection.execute(
                "INSERT INTO experiment (id, task_id, task_name, config_snapshot) VALUES (?, ?, ?, ?)",
                ("exp3", "task1", "Test", "{}"),
            )

        assert db.fetchone("SELECT 1 FROM experiment WHERE id = ?", ("exp3",))

    def test_uow_rollback_on_error(self, db: Database):
        """UnitOfWork 异常回滚."""
        uow = UnitOfWork(db)
        try:
            with uow:
                uow.connection.execute(
                    "INSERT INTO experiment (id, task_id, task_name, config_snapshot) VALUES (?, ?, ?, ?)",
                    ("exp4", "task1", "Test", "{}"),
                )
                raise RuntimeError("Test error")
        except RuntimeError:
            pass

        assert not db.fetchone("SELECT 1 FROM experiment WHERE id = ?", ("exp4",))

    def test_atomic_context_manager(self, db: Database):
        """atomic 上下文管理器."""
        with atomic(db) as conn:
            conn.execute(
                "INSERT INTO experiment (id, task_id, task_name, config_snapshot) VALUES (?, ?, ?, ?)",
                ("exp5", "task1", "Test", "{}"),
            )

        assert db.fetchone("SELECT 1 FROM experiment WHERE id = ?", ("exp5",))


class TestConcurrency:
    """并发测试."""

    def test_concurrent_reads(self, db_path):
        """并发读取应稳定."""
        # 初始化数据库
        db = Database(db_path)
        initialize_database(db)
        db.execute(
            "INSERT INTO experiment (id, task_id, task_name, config_snapshot) VALUES (?, ?, ?, ?)",
            ("exp1", "task1", "Test", "{}"),
        )
        db.close()

        errors = []
        results = []

        def reader():
            try:
                local_db = Database(db_path)
                for _ in range(10):
                    row = local_db.fetchone("SELECT * FROM experiment WHERE id = ?", ("exp1",))
                    if row:
                        results.append(row["id"])
                    time.sleep(0.001)
                local_db.close()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=reader) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Errors during concurrent reads: {errors}"
        assert len(results) == 50  # 5 threads * 10 reads

    def test_concurrent_writes(self, db_path):
        """并发写入应通过 busy_timeout 排队."""
        db = Database(db_path)
        initialize_database(db)
        db.close()

        errors = []
        success_count = [0]
        lock = threading.Lock()

        def writer(thread_id: int):
            try:
                local_db = Database(db_path, busy_timeout=10000)
                for i in range(5):
                    with local_db.transaction() as conn:
                        conn.execute(
                            "INSERT INTO experiment (id, task_id, task_name, config_snapshot) VALUES (?, ?, ?, ?)",
                            (f"exp_{thread_id}_{i}", "task1", "Test", "{}"),
                        )
                    with lock:
                        success_count[0] += 1
                local_db.close()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Errors during concurrent writes: {errors}"
        assert success_count[0] == 15  # 3 threads * 5 writes

    def test_read_during_write(self, db_path):
        """写入期间的读取应成功（WAL 特性）."""
        db = Database(db_path)
        initialize_database(db)
        db.execute(
            "INSERT INTO experiment (id, task_id, task_name, config_snapshot) VALUES (?, ?, ?, ?)",
            ("exp_initial", "task1", "Initial", "{}"),
        )
        db.close()

        read_results = []
        write_done = threading.Event()

        def writer():
            local_db = Database(db_path)
            with local_db.transaction() as conn:
                conn.execute(
                    "INSERT INTO experiment (id, task_id, task_name, config_snapshot) VALUES (?, ?, ?, ?)",
                    ("exp_write", "task1", "Write", "{}"),
                )
                time.sleep(0.1)  # 保持事务打开
            write_done.set()
            local_db.close()

        def reader():
            local_db = Database(db_path)
            # 在写入事务期间读取
            row = local_db.fetchone("SELECT * FROM experiment WHERE id = ?", ("exp_initial",))
            read_results.append(row is not None)
            local_db.close()

        writer_thread = threading.Thread(target=writer)
        reader_thread = threading.Thread(target=reader)

        writer_thread.start()
        time.sleep(0.05)  # 确保写入事务已开始
        reader_thread.start()

        writer_thread.join()
        reader_thread.join()

        assert read_results[0] is True  # 读取应成功


class TestUnitOfWorkNested:
    """嵌套事务测试."""

    def test_nested_savepoint(self, db: Database):
        """嵌套事务使用 savepoint."""
        uow = UnitOfWork(db)

        uow.begin()
        uow.connection.execute(
            "INSERT INTO experiment (id, task_id, task_name, config_snapshot) VALUES (?, ?, ?, ?)",
            ("exp_outer", "task1", "Outer", "{}"),
        )

        # 嵌套事务
        uow.begin()
        uow.connection.execute(
            "INSERT INTO experiment (id, task_id, task_name, config_snapshot) VALUES (?, ?, ?, ?)",
            ("exp_inner", "task1", "Inner", "{}"),
        )
        uow.commit()  # 释放 savepoint

        uow.commit()  # 提交外层事务

        assert db.fetchone("SELECT 1 FROM experiment WHERE id = ?", ("exp_outer",))
        assert db.fetchone("SELECT 1 FROM experiment WHERE id = ?", ("exp_inner",))

    def test_nested_rollback(self, db: Database):
        """嵌套事务回滚不影响外层."""
        uow = UnitOfWork(db)

        uow.begin()
        uow.connection.execute(
            "INSERT INTO experiment (id, task_id, task_name, config_snapshot) VALUES (?, ?, ?, ?)",
            ("exp_outer2", "task1", "Outer", "{}"),
        )

        # 嵌套事务回滚
        uow.begin()
        uow.connection.execute(
            "INSERT INTO experiment (id, task_id, task_name, config_snapshot) VALUES (?, ?, ?, ?)",
            ("exp_inner2", "task1", "Inner", "{}"),
        )
        uow.rollback()  # 回滚 savepoint

        uow.commit()

        assert db.fetchone("SELECT 1 FROM experiment WHERE id = ?", ("exp_outer2",))
        assert not db.fetchone("SELECT 1 FROM experiment WHERE id = ?", ("exp_inner2",))
