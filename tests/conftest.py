"""Pytest shared fixtures.

提供跨测试文件的通用 fixture，减少重复定义。
"""

from __future__ import annotations

import pytest

from omnievolve.storage.artifact_store import ArtifactStore
from omnievolve.storage.db import create_memory_database
from omnievolve.storage.migrations import initialize_database
from omnievolve.storage.repositories.experiment_repo import ExperimentRepository


@pytest.fixture
def db():
    """创建内存数据库并运行迁移."""
    database = create_memory_database()
    initialize_database(database)
    yield database
    database.close()


@pytest.fixture
def artifact_store(db, tmp_path):
    """创建临时文件 ArtifactStore."""
    store = tmp_path / "artifacts"
    return ArtifactStore(store, db)


@pytest.fixture
def experiment(db):
    """创建测试实验."""
    repo = ExperimentRepository(db)
    exp = repo.create(task_id="test", task_name="test-task", config_snapshot={})
    return exp.id
