"""Repository base.py 单元测试 — Repository 协议 + BaseRepository + 辅助函数."""

from __future__ import annotations

import pytest

from omnievolve.storage.db import create_memory_database
from omnievolve.storage.migrations import initialize_database
from omnievolve.storage.repositories.base import (
    BaseRepository,
    Repository,
    generate_id,
    now_iso,
)

pytestmark = pytest.mark.unit


@pytest.fixture
def db():
    database = create_memory_database()
    initialize_database(database)
    yield database
    database.close()


class TestGenerateId:
    def test_generate_id_returns_nonempty(self):
        assert len(generate_id()) > 0

    def test_generate_id_is_unique(self):
        ids = {generate_id() for _ in range(100)}
        assert len(ids) == 100

    def test_generate_id_is_hex_string(self):
        id_ = generate_id()
        assert all(c in "0123456789abcdef" for c in id_)


class TestNowIso:
    def test_now_iso_is_valid_format(self):
        ts = now_iso()
        assert "T" in ts  # ISO 8601
        assert ts.endswith("+00:00") or ts.endswith("Z")

    def test_now_iso_is_current(self):
        ts = now_iso()
        assert ts.startswith("202")  # 年份在当前世纪


class TestRepositoryProtocol:
    def test_base_repository_is_instance(self):
        class MyRepo(BaseRepository[str]):
            table_name = "test"

            def _row_to_entity(self, row):
                return str(row)

            def _entity_to_dict(self, entity):
                return {"val": entity}

        # BaseRepository 实现 Repository Protocol
        assert isinstance(MyRepo(None), Repository)  # type: ignore[arg-type]
