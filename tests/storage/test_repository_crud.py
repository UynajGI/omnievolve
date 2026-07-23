"""BaseRepository CRUD 测试 — Step 12: 39% → 80%+."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from omnievolve.storage.db import create_memory_database
from omnievolve.storage.migrations import initialize_database
from omnievolve.storage.repositories.base import BaseRepository


@dataclass
class SimpleEntity:
    """测试用简单实体."""

    id: str
    name: str
    status: str = "active"
    meta: dict | None = None


class SimpleRepo(BaseRepository[SimpleEntity]):
    """绑定到 candidate 表的测试 Repository."""

    table_name = "candidate"

    def _row_to_entity(self, row) -> SimpleEntity:
        import json

        meta = json.loads(row["meta"]) if row["meta"] else None
        return SimpleEntity(
            id=row["id"],
            name=row["task_id"],
            status=row["status"],
            meta=meta,
        )

    def _entity_to_dict(self, entity: SimpleEntity) -> dict:
        import json

        return {
            "id": entity.id,
            "experiment_id": "test-exp",
            "task_id": entity.name,
            "generation": 0,
            "artifact_hash": "test-hash",
            "search_policy_id": "default",
            "status": entity.status,
            "meta": json.dumps(entity.meta) if entity.meta else None,
        }


@pytest.fixture
def db():
    database = create_memory_database()
    initialize_database(database)
    # 创建测试用 experiment
    database.execute(
        "INSERT INTO experiment (id, task_id, task_name, config_snapshot) VALUES (?, ?, ?, ?)",
        ("test-exp", "test", "test", "{}"),
    )
    # 创建测试用 artifact（满足 FK 约束）
    database.execute(
        "INSERT OR IGNORE INTO artifact (hash, artifact_type, byte_size, relative_path) "
        "VALUES ('test-hash', 'source', 100, 'artifacts/te/test-hash')"
    )
    yield database
    database.close()


@pytest.fixture
def repo(db):
    return SimpleRepo(db)


class TestBaseRepositoryCRUD:
    """BaseRepository CRUD 测试."""

    def test_create_and_get(self, repo):
        entity = SimpleEntity(id="e1", name="test-entity")
        repo.create(entity)
        loaded = repo.get("e1")
        assert loaded is not None
        assert loaded.name == "test-entity"

    def test_get_nonexistent(self, repo):
        assert repo.get("nonexistent") is None

    def test_list_all(self, repo):
        repo.create(SimpleEntity(id="e1", name="a"))
        repo.create(SimpleEntity(id="e2", name="b"))
        entities = repo.list()
        assert len(entities) >= 2

    def test_list_with_filters(self, repo):
        repo.create(SimpleEntity(id="e1", name="a", status="active"))
        repo.create(SimpleEntity(id="e2", name="b", status="inactive"))
        active = repo.list(status="active")
        assert all(e.status == "active" for e in active)

    def test_list_pagination(self, repo):
        for i in range(5):
            repo.create(SimpleEntity(id=f"e{i}", name=f"entity-{i}"))
        page1 = repo.list(limit=2, offset=0)
        page2 = repo.list(limit=2, offset=2)
        assert len(page1) == 2
        assert len(page2) == 2
        assert page1[0].id != page2[0].id

    def test_delete_existing(self, repo):
        repo.create(SimpleEntity(id="e1", name="to-delete"))
        assert repo.delete("e1") is True
        assert repo.get("e1") is None

    def test_delete_nonexistent(self, repo):
        assert repo.delete("nonexistent") is False

    def test_count(self, repo):
        repo.create(SimpleEntity(id="e1", name="a"))
        repo.create(SimpleEntity(id="e2", name="b"))
        assert repo.count() >= 2

    def test_count_with_filters(self, repo):
        repo.create(SimpleEntity(id="e1", name="a", status="active"))
        repo.create(SimpleEntity(id="e2", name="b", status="inactive"))
        assert repo.count(status="active") >= 1

    def test_exists(self, repo):
        repo.create(SimpleEntity(id="e1", name="a"))
        assert repo.exists("e1") is True
        assert repo.exists("nonexistent") is False

    def test_create_with_json_meta(self, repo):
        entity = SimpleEntity(id="e1", name="a", meta={"key": "value"})
        repo.create(entity)
        loaded = repo.get("e1")
        assert loaded.meta == {"key": "value"}
