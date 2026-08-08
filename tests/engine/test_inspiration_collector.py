"""InspirationCollector 测试 — 档 1: reference-edge 跨分支回流 + 完整代码注入."""

from __future__ import annotations

import uuid

import pytest

from omnievolve.engine.inspiration import InspirationCollector
from omnievolve.storage.artifact_store import ArtifactStore
from omnievolve.storage.db import create_memory_database
from omnievolve.storage.migrations import initialize_database
from omnievolve.storage.repositories.candidate_repo import CandidateRepository
from omnievolve.storage.repositories.experiment_repo import ExperimentRepository


@pytest.fixture
def db(tmp_path):
    database = create_memory_database()
    initialize_database(database)
    database.execute(
        "INSERT OR IGNORE INTO embedding_profile (id, purpose, provider, model, dimension, collection_path) "
        "VALUES ('profile-code-default', 'code', 'local', 'test', 128, '/tmp/test')"
    )
    database.execute(
        "INSERT OR IGNORE INTO task_evaluator_version (id, name, semantic_version, implementation_hash, task_semantics_hash, score_schema) "
        "VALUES ('eval@1', 'test-eval', '1.0', 'hash', 'hash', '{}')"
    )
    database.execute(
        "INSERT OR IGNORE INTO execution_environment_version (id, backend, resource_policy, network_policy) "
        "VALUES ('env@1', 'subprocess', '{}', '{}')"
    )
    database.execute(
        "INSERT OR IGNORE INTO search_policy_version (id, experiment_id, version, genome, risk_level, status) "
        "VALUES ('default', NULL, 1, '{}', 'L0', 'champion')"
    )
    yield database
    database.close()


@pytest.fixture
def store(db, tmp_path):
    return ArtifactStore(tmp_path / "artifacts", db)


@pytest.fixture
def artifacts(db, tmp_path, store):
    codes = {
        "AAA": "def high():\n    return 0.9\n",
        "BBB": "def mid():\n    return 0.7\n",
        "CCC": "def low():\n    return 0.4\n",
    }
    hashes = {}
    for name, code in codes.items():
        hashes[name] = store.store_text(code, artifact_type="source")
        db.execute(
            "INSERT OR IGNORE INTO artifact (hash, artifact_type, byte_size, relative_path) "
            "VALUES (?, 'source', ?, ?)",
            (hashes[name], len(code), f"artifacts/{hashes[name]}"),
        )
    return hashes


@pytest.fixture
def experiment(db):
    repo = ExperimentRepository(db)
    return repo.create(task_id="t", task_name="t", config_snapshot={}).id


def _add_candidate(db, experiment: str, artifact_hash: str, gen: int, score: float) -> str:
    cid = uuid.uuid4().hex
    db.execute(
        "INSERT INTO candidate (id, experiment_id, task_id, generation, artifact_hash, search_policy_id, status) "
        "VALUES (?, ?, 't', ?, ?, 'default', 'evaluated')",
        (cid, experiment, gen, artifact_hash),
    )
    db.execute(
        "INSERT INTO evaluation_run (candidate_id, experiment_id, evaluator_version_id, environment_version_id, "
        "status, passed, primary_score) VALUES (?, ?, 'eval@1', 'env@1', 'completed', 1, ?)",
        (cid, experiment, score),
    )
    return cid


class TestReferenceEdgeFlowback:
    """档 1 核心：被引用高分候选完整代码回流."""

    def test_reference_edge_injected_with_full_code(self, db, artifacts, store, experiment):
        """cross_branch 引用的高分候选以完整代码注入（source=reference_edge）."""
        exp = experiment
        a = _add_candidate(db, exp, artifacts["AAA"], 0, 0.9)
        b = _add_candidate(db, exp, artifacts["BBB"], 0, 0.7)
        parent = _add_candidate(db, exp, artifacts["CCC"], 1, 0.4)

        # parent 曾引用 A、B（cross_branch 边）
        for src in (a, b):
            db.execute(
                "INSERT INTO candidate_reference_edge (src_candidate_id, dst_candidate_id, reference_type, detail) "
                "VALUES (?, ?, 'cross_branch', 'source=top_k')",
                (src, parent),
            )

        collector = InspirationCollector(db, CandidateRepository(db), store)
        result = collector.collect_inspiration(
            exp, "eval@1", "env@1", [parent], top_k=0, random_k=0, reference_k=1
        )

        edges = [i for i in result if i["source"] == "reference_edge"]
        assert len(edges) == 1, f"应返回 1 个 reference_edge, 实际 {len(edges)}"
        assert edges[0]["candidate_id"] == a
        assert edges[0]["code"] == "def high():\n    return 0.9\n"  # 完整代码
        assert edges[0]["score"] == 0.9

    def test_dedup_across_sources(self, db, artifacts, store, experiment):
        """同一候选同时是 top_k 和被引用时只出现一次."""
        exp = experiment
        a = _add_candidate(db, exp, artifacts["AAA"], 0, 0.9)
        parent = _add_candidate(db, exp, artifacts["CCC"], 1, 0.4)
        db.execute(
            "INSERT INTO candidate_reference_edge (src_candidate_id, dst_candidate_id, reference_type, detail) "
            "VALUES (?, ?, 'cross_branch', 'source=top_k')",
            (a, parent),
        )

        collector = InspirationCollector(db, CandidateRepository(db), store)
        result = collector.collect_inspiration(
            exp, "eval@1", "env@1", [parent], top_k=2, random_k=0, reference_k=1
        )

        ids = [i["candidate_id"] for i in result]
        assert ids.count(a) == 1, f"候选 {a} 应只出现一次: {ids}"

    def test_full_code_not_preview(self, db, artifacts, store, experiment):
        """所有来源注入完整 code 字段（不再是 code_preview 截断）."""
        exp = experiment
        a = _add_candidate(db, exp, artifacts["AAA"], 0, 0.9)
        parent = _add_candidate(db, exp, artifacts["CCC"], 1, 0.4)
        db.execute(
            "INSERT INTO candidate_reference_edge (src_candidate_id, dst_candidate_id, reference_type, detail) "
            "VALUES (?, ?, 'cross_branch', 'source=top_k')",
            (a, parent),
        )

        collector = InspirationCollector(db, CandidateRepository(db), store)
        result = collector.collect_inspiration(
            exp, "eval@1", "env@1", [parent], top_k=1, random_k=1, reference_k=1
        )

        assert result, "应有 inspiration"
        for item in result:
            assert "code" in item, f"{item['source']} 应含完整 code"
            assert item["code"] in ("def high():\n    return 0.9\n", "def mid():\n    return 0.7\n")
            assert "code_preview" not in item

    def test_exclude_parents_from_reference(self, db, artifacts, store, experiment):
        """被引用者中排除当前 parent（自身不被当作跨分支参考）."""
        exp = experiment
        a = _add_candidate(db, exp, artifacts["AAA"], 0, 0.9)
        b = _add_candidate(db, exp, artifacts["BBB"], 0, 0.7)
        parent = _add_candidate(db, exp, artifacts["CCC"], 1, 0.4)
        # 三向互引，parent 也是其他候选的 src
        for src in (a, b, parent):
            db.execute(
                "INSERT INTO candidate_reference_edge (src_candidate_id, dst_candidate_id, reference_type, detail) "
                "VALUES (?, ?, 'cross_branch', 'source=top_k')",
                (src, parent if src != parent else a),
            )

        collector = InspirationCollector(db, CandidateRepository(db), store)
        result = collector.collect_inspiration(
            exp, "eval@1", "env@1", [parent], top_k=0, random_k=0, reference_k=2
        )

        ref_ids = {i["candidate_id"] for i in result if i["source"] == "reference_edge"}
        assert parent not in ref_ids
        assert ref_ids == {a, b}
