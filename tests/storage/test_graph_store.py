"""graph_store.py 单元测试 — GraphStore 图加载与导出."""

from __future__ import annotations

import pytest

from omnievolve.storage.db import create_memory_database
from omnievolve.storage.graph_store import GraphStore
from omnievolve.storage.migrations import initialize_database

pytestmark = pytest.mark.unit


@pytest.fixture
def db():
    database = create_memory_database()
    initialize_database(database)
    yield database
    database.close()


@pytest.fixture
def store(db):
    return GraphStore(db)


def _seed_candidates(db, experiment_id: str) -> list[str]:
    """播种候选和血缘数据."""
    db.execute(
        "INSERT OR IGNORE INTO experiment (id, task_id, task_name, config_snapshot) "
        "VALUES (?, ?, ?, '{}')",
        (experiment_id, "task", "Task"),
    )
    for i in range(3):
        db.execute(
            "INSERT OR IGNORE INTO artifact (hash, artifact_type, byte_size, relative_path) "
            "VALUES (?, 'source', 10, ?)",
            (f"hash_{i}", f"sha256/ab/cd/hash_{i}"),
        )
    db.execute(
        "INSERT OR IGNORE INTO search_policy_version "
        "(id, experiment_id, version, genome, status) "
        "VALUES ('policy', ?, 0, '{}', 'champion')",
        (experiment_id,),
    )
    ids = []
    for i in range(3):
        cid = f"c{i}"
        db.execute(
            "INSERT INTO candidate (id, experiment_id, task_id, generation, "
            "artifact_hash, search_policy_id, status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (cid, experiment_id, "task", i, f"hash_{i}", "policy", "evaluated"),
        )
        ids.append(cid)
    if len(ids) >= 2:
        db.execute(
            "INSERT INTO candidate_lineage (child_id, parent_id, relation_type) VALUES (?, ?, ?)",
            (ids[1], ids[0], "mutate"),
        )
    if len(ids) >= 3:
        db.execute(
            "INSERT INTO candidate_lineage (child_id, parent_id, relation_type) VALUES (?, ?, ?)",
            (ids[2], ids[1], "mutate"),
        )
    return ids


class TestGraphStore:
    def test_load_subgraph_empty(self, store):
        graph = store.load_subgraph("nonexistent")
        assert graph.number_of_nodes() == 0

    def test_load_subgraph_with_candidates(self, db, store):
        ids = _seed_candidates(db, "exp-1")
        graph = store.load_subgraph("exp-1")
        assert graph.number_of_nodes() >= len(ids)

    def test_load_subgraph_includes_edges(self, db, store):
        _seed_candidates(db, "exp-2")
        graph = store.load_subgraph("exp-2")
        assert graph.number_of_edges() >= 2

    def test_load_subgraph_with_root_ids(self, db, store):
        ids = _seed_candidates(db, "exp-3")
        graph = store.load_subgraph("exp-3", root_ids=[ids[0]])
        assert graph.number_of_nodes() >= 1

    def test_get_stagnant_branches_empty(self, db, store):
        _seed_candidates(db, "exp-4")
        stagnant = store.get_stagnant_branches("exp-4", threshold_gens=5)
        assert isinstance(stagnant, list)

    def test_get_diverse_elites(self, db, store):
        _seed_candidates(db, "exp-5")
        # 需要 evaluation_run 数据，没有则返回空
        elites = store.get_diverse_elites("exp-5", top_k=3)
        assert isinstance(elites, list)

    def test_export_graphml(self, db, store, tmp_path):
        """GraphML 导出（需要先替换 None 值）."""
        _seed_candidates(db, "exp-6")
        import networkx as nx

        graph = store.load_subgraph("exp-6")
        # GraphML 不支持 None 值，需要先转换
        for _, attrs in graph.nodes(data=True):
            for k, v in list(attrs.items()):
                if v is None:
                    attrs[k] = ""
        out = tmp_path / "graph.graphml"
        nx.write_graphml(graph, str(out))
        assert out.exists()
