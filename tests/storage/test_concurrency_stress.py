"""SQLite 并发压力测试 — WAL 模式多线程读写.

验证 Database 类在真实并发负载下的正确性:
  - 多线程同时写入无 "database is locked"
  - 读写并发不互相阻塞
  - WAL 模式事务隔离正确
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Event, Lock

import pytest

from omnievolve.storage.db import Database


def _write_worker(db_path: str, worker_id: int, count: int, results: list):
    """Worker thread: insert rows into its own table."""
    db = Database(db_path)
    conn = db.get_connection()
    try:
        conn.execute(
            f"CREATE TABLE IF NOT EXISTS stress_test_{worker_id} (id INTEGER PRIMARY KEY, val TEXT)"
        )
        for i in range(count):
            conn.execute(
                f"INSERT INTO stress_test_{worker_id} (val) VALUES (?)",
                (f"w{worker_id}-{i}",),
            )
        # Verify
        row = conn.execute(f"SELECT COUNT(*) FROM stress_test_{worker_id}").fetchone()
        results.append((worker_id, row[0]))
    finally:
        db.close()


def _mixed_worker(db_path: str, worker_id: int, iterations: int, results: list):
    """Worker thread: read + write, verify isolation."""
    db = Database(db_path)
    conn = db.get_connection()
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS mixed_test (id INTEGER PRIMARY KEY, worker_id INTEGER, seq INTEGER)"
        )
        for i in range(iterations):
            conn.execute(
                "INSERT INTO mixed_test (worker_id, seq) VALUES (?, ?)",
                (worker_id, i),
            )
            # Read back — should see own writes
            row = conn.execute(
                "SELECT MAX(seq) FROM mixed_test WHERE worker_id = ?",
                (worker_id,),
            ).fetchone()
            assert row[0] == i, f"Worker {worker_id} expected seq {i}, got {row[0]}"
    finally:
        conn.execute("DROP TABLE IF EXISTS mixed_test")
        db.close()
    results.append(worker_id)


@pytest.fixture
def tmp_db_path(tmp_path):
    """Temporary DB file for concurrency tests."""
    return str(tmp_path / "concurrency_test.db")


class TestConcurrentWrites:
    """Multiple threads writing to separate tables concurrently."""

    def test_parallel_writers_no_lock_error(self, tmp_db_path):
        workers = 4
        rows_per_worker = 50
        results = []

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [
                executor.submit(_write_worker, tmp_db_path, i, rows_per_worker, results)
                for i in range(workers)
            ]
            for f in as_completed(futures):
                f.result()  # raises on exception

        # All workers completed, each wrote exactly rows_per_worker rows
        assert len(results) == workers
        for worker_id, count in results:
            assert count == rows_per_worker, f"Worker {worker_id} got {count}"

    def test_writers_and_readers(self, tmp_db_path):
        """Concurrent reads while writes are happening."""
        # First, setup a table with initial data
        db = Database(tmp_db_path)
        db.execute("CREATE TABLE IF NOT EXISTS shared (id INTEGER PRIMARY KEY, val TEXT)")
        db.execute("INSERT INTO shared (val) VALUES ('initial')")
        db.close()

        errors = []
        read_results = []
        writes_visible = Event()
        write_count = 0
        write_count_lock = Lock()

        def writer(db_path, n):
            nonlocal write_count
            db = Database(db_path)
            try:
                for i in range(n):
                    db.execute("INSERT INTO shared (val) VALUES (?)", (f"w-{i}",))
                    with write_count_lock:
                        write_count += 1
                        if write_count >= 2:
                            writes_visible.set()
            except Exception as e:
                errors.append(f"writer: {e}")
            finally:
                db.close()

        def reader(db_path, n, results):
            db = Database(db_path)
            try:
                if not writes_visible.wait(timeout=5):
                    errors.append("reader: writers did not publish rows in time")
                    return
                for _ in range(n):
                    cursor = db.execute("SELECT COUNT(*) FROM shared")
                    count = cursor.fetchone()[0]
                    results.append(count)
            except Exception as e:
                errors.append(f"reader: {e}")
            finally:
                db.close()

        with ThreadPoolExecutor(max_workers=6) as executor:
            futures = [
                executor.submit(writer, tmp_db_path, 30),
                executor.submit(writer, tmp_db_path, 30),
                executor.submit(reader, tmp_db_path, 100, read_results),
                executor.submit(reader, tmp_db_path, 100, read_results),
            ]
            for f in as_completed(futures):
                f.result()

        assert not errors, f"Unexpected errors: {errors}"
        # Readers start after two autocommit writes are visible.
        assert all(c >= 3 for c in read_results)

    def test_wal_isolation(self, tmp_db_path):
        """WAL mode: writers don't block readers, readers see committed state."""
        db = Database(tmp_db_path)
        db.execute("CREATE TABLE IF NOT EXISTS wal_test (id INTEGER PRIMARY KEY, val TEXT)")
        db.execute("INSERT INTO wal_test (val) VALUES ('before')")
        db.close()

        checkpoint = {"reader_saw": None}

        def blocking_writer(db_path):
            db = Database(db_path)
            conn = db.get_connection()
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("INSERT INTO wal_test (val) VALUES ('during')")
            time.sleep(0.1)  # Hold transaction open
            conn.execute("COMMIT")
            db.close()

        def concurrent_reader(db_path):
            time.sleep(0.02)  # Start after writer begins
            db = Database(db_path)
            row = db.execute("SELECT COUNT(*) FROM wal_test").fetchone()
            checkpoint["reader_saw"] = row[0]
            db.close()

        with ThreadPoolExecutor(max_workers=2) as executor:
            f1 = executor.submit(blocking_writer, tmp_db_path)
            f2 = executor.submit(concurrent_reader, tmp_db_path)
            f1.result()
            f2.result()

        # Reader should see 1 (committed before writer started), not 2
        assert checkpoint["reader_saw"] == 1


class TestWALModeEnabled:
    def test_wal_mode_active(self, tmp_db_path):
        db = Database(tmp_db_path, wal=True)
        row = db.execute("PRAGMA journal_mode").fetchone()
        assert row[0].lower() == "wal"
        db.close()

    def test_foreign_keys_active(self, tmp_db_path):
        db = Database(tmp_db_path, foreign_keys=True)
        row = db.execute("PRAGMA foreign_keys").fetchone()
        assert row[0] == 1
        db.close()

    def test_memory_db_also_wal(self):
        db = Database(":memory:", wal=True)
        row = db.execute("PRAGMA journal_mode").fetchone()
        # :memory: defaults to memory journal mode, WAL may or may not apply
        assert row[0].lower() in ("wal", "memory")
        db.close()
