"""Schema 完整性与约束测试.

S1-13: 实现数据库完整性与约束测试
- 非法父代、跨实验引用、重复版本、孤儿记录均被拒绝
"""

import pytest

from omnievolve.storage.db import Database, create_memory_database
from omnievolve.storage.migrations import get_schema_version, initialize_database


@pytest.fixture
def db():
    """创建已初始化的内存数据库."""
    database = create_memory_database()
    initialize_database(database)
    yield database
    database.close()


class TestSchemaCreation:
    """测试 Schema 创建."""

    def test_schema_version_created(self, db: Database):
        """schema_version 表应存在并有初始版本."""
        version = get_schema_version(db)
        assert version == 1

    def test_all_tables_created(self, db: Database):
        """所有核心表应存在."""
        tables = db.fetchall("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        table_names = {row["name"] for row in tables}

        expected_tables = {
            "schema_version",
            "experiment",
            "artifact",
            "thought_record",
            "candidate",
            "candidate_lineage",
            "candidate_reference_edge",
            "candidate_search_state",
            "task_evaluator_version",
            "execution_environment_version",
            "evaluation_run",
            "search_policy_version",
            "policy_experiment",
            "meta_evaluation_window",
            "memory_entry",
            "prompt_version",
            "embedding_profile",
            "vector_index_job",
            "job",
            "llm_call_ledger",
        }

        for table in expected_tables:
            assert table in table_names, f"Table {table} not found"

    def test_migration_idempotent(self, db: Database):
        """迁移应幂等."""
        from omnievolve.storage.migrations import migrate

        # 再次运行迁移不应报错
        version = migrate(db)
        assert version == 1


class TestForeignKeys:
    """测试外键约束."""

    def test_candidate_requires_experiment(self, db: Database):
        """Candidate 必须引用存在的 experiment."""
        # 先创建 artifact
        db.execute(
            "INSERT INTO artifact (hash, artifact_type, byte_size, relative_path) VALUES (?, ?, ?, ?)",
            ("abc123", "source", 100, "sha256/ab/c1/abc123"),
        )

        with pytest.raises(Exception):  # IntegrityError
            db.execute(
                """
                INSERT INTO candidate (id, experiment_id, task_id, generation, artifact_hash, search_policy_id)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                ("cand1", "nonexistent_exp", "task1", 1, "abc123", "policy1"),
            )

    def test_lineage_requires_valid_candidates(self, db: Database):
        """Lineage 必须引用存在的 candidate."""
        with pytest.raises(Exception):
            db.execute(
                """
                INSERT INTO candidate_lineage (child_id, parent_id, relation_type)
                VALUES (?, ?, ?)
                """,
                ("nonexistent_child", "nonexistent_parent", "mutate"),
            )

    def test_evaluation_run_requires_candidate(self, db: Database):
        """EvaluationRun 必须引用存在的 candidate."""
        with pytest.raises(Exception):
            db.execute(
                """
                INSERT INTO evaluation_run (id, experiment_id, candidate_id, evaluator_version_id, environment_version_id)
                VALUES (?, ?, ?, ?, ?)
                """,
                ("run1", "exp1", "nonexistent_cand", "eval1", "env1"),
            )


class TestUniqueConstraints:
    """测试唯一约束."""

    def test_evaluator_version_unique(self, db: Database):
        """评估器版本 (name, semantic_version, implementation_hash) 应唯一."""
        db.execute(
            """
            INSERT INTO task_evaluator_version
                (id, name, semantic_version, implementation_hash, task_semantics_hash, score_schema)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("eval1", "test-eval", "1.0.0", "hash1", "sem_hash1", "{}"),
        )

        with pytest.raises(Exception):  # IntegrityError
            db.execute(
                """
                INSERT INTO task_evaluator_version
                    (id, name, semantic_version, implementation_hash, task_semantics_hash, score_schema)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                ("eval2", "test-eval", "1.0.0", "hash1", "sem_hash2", "{}"),
            )

    def test_policy_version_unique_per_experiment(self, db: Database):
        """每个实验的策略版本应唯一."""
        db.execute(
            "INSERT INTO experiment (id, task_id, task_name, config_snapshot) VALUES (?, ?, ?, ?)",
            ("exp1", "task1", "Test Task", "{}"),
        )

        db.execute(
            """
            INSERT INTO search_policy_version (id, experiment_id, version, genome)
            VALUES (?, ?, ?, ?)
            """,
            ("policy1", "exp1", 1, "{}"),
        )

        with pytest.raises(Exception):
            db.execute(
                """
                INSERT INTO search_policy_version (id, experiment_id, version, genome)
                VALUES (?, ?, ?, ?)
                """,
                ("policy2", "exp1", 1, "{}"),
            )


class TestDataIntegrity:
    """测试数据完整性."""

    def test_experiment_lifecycle(self, db: Database):
        """实验生命周期数据完整性."""
        db.execute(
            """
            INSERT INTO experiment (id, task_id, task_name, status, config_snapshot)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("exp1", "task1", "Test Task", "created", '{"key": "value"}'),
        )

        row = db.fetchone("SELECT * FROM experiment WHERE id = ?", ("exp1",))
        assert row is not None
        assert row["task_id"] == "task1"
        assert row["status"] == "created"
        assert row["total_tokens"] == 0

    def test_artifact_reference_integrity(self, db: Database):
        """Artifact 引用完整性."""
        # 创建基础 artifact
        db.execute(
            "INSERT INTO artifact (hash, artifact_type, byte_size, relative_path) VALUES (?, ?, ?, ?)",
            ("base_hash", "source", 100, "sha256/ba/se/base_hash"),
        )

        # 创建引用基础 artifact 的 diff
        db.execute(
            """
            INSERT INTO artifact (hash, artifact_type, byte_size, relative_path, base_artifact_hash)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("diff_hash", "diff", 50, "sha256/di/ff/diff_hash", "base_hash"),
        )

        row = db.fetchone("SELECT base_artifact_hash FROM artifact WHERE hash = ?", ("diff_hash",))
        assert row["base_artifact_hash"] == "base_hash"
