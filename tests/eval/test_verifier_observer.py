"""VerifierObserver 集成测试（集成计划 §9.1/§16.2）.

核心断言：
- observer 只写证据（verification_batch/comparison + artifact），
  绝不修改 passed/primary_score/search 状态；
- 只对通过硬正确性测试且有 parent 的候选触发；
- 证据包含候选与 peer 摘要，且不含隐藏测试数据。
"""

from __future__ import annotations

import json

import pytest

from omnievolve.eval.fake_verifier import FakeProbabilisticVerifier
from omnievolve.eval.task_evaluator import EvalOutput
from omnievolve.eval.verification_service import VerificationService
from omnievolve.eval.verifier_observer import VerifierObserver

CRITERIA = ("specification_fidelity", "mechanism_realization", "evidence_consistency")


def _make_candidate(db, artifact_store, *, candidate_id, experiment_id, task_id, code):
    db.execute(
        """
        INSERT OR IGNORE INTO experiment
            (id, task_id, task_name, status, config_snapshot)
        VALUES (?, ?, ?, 'created', '{}')
        """,
        (experiment_id, task_id, task_id),
    )
    _ensure_eval_versions(db)
    artifact_hash = artifact_store.store_text(code, "source")
    db.execute(
        """
        INSERT INTO candidate
            (id, experiment_id, task_id, generation, island_id, artifact_hash,
             search_policy_id, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            candidate_id,
            experiment_id,
            task_id,
            1,
            "island-1",
            artifact_hash,
            "policy-1",
            "evaluated",
        ),
    )
    return artifact_hash


def _ensure_eval_versions(db):
    """FK：evaluation_run 引用 evaluator/environment 版本表."""
    db.execute(
        """
        INSERT OR IGNORE INTO task_evaluator_version
            (id, name, semantic_version, implementation_hash,
             task_semantics_hash, score_schema)
        VALUES ('eval-v1', 'sort', '1.0.0', 'h', 'h', '{}')
        """
    )
    db.execute(
        """
        INSERT OR IGNORE INTO execution_environment_version
            (id, backend, resource_policy, network_policy)
        VALUES ('env-v1', 'trusted_subprocess', '{}', 'none')
        """
    )


def _make_eval_run(db, *, candidate_id, experiment_id, score, passed=True):
    db.execute(
        """
        INSERT INTO evaluation_run
            (id, experiment_id, candidate_id, evaluator_version_id,
             environment_version_id, seed, split_name, attempt, status,
             passed, primary_score, metrics, execution_time_ms, finished_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            f"run-{candidate_id}",
            experiment_id,
            candidate_id,
            "eval-v1",
            "env-v1",
            0,
            "default",
            1,
            "completed",
            int(passed),
            score,
            json.dumps({}),
            10.0,
            "2026-08-01T00:00:00Z",
        ),
    )


def _observer(db, artifact_store, *, fail_closed=False):
    service = VerificationService(
        db,
        artifact_store,
        model="verifier-model",
        prompt_version_id="verifier-observer-v1",
        granularity=5,
        repetitions=2,
        criteria=CRITERIA,
        order_seed=42,
        mode="observer",
        fail_closed=fail_closed,
    )
    return VerifierObserver(
        service,
        FakeProbabilisticVerifier(),
        criteria=CRITERIA,
        granularity=5,
        repetitions=2,
        order_seed=42,
    )


@pytest.fixture
def search_state_snapshot(db):
    """采集搜索相关表的行数，用于验证 observer 无副作用."""

    def snapshot():
        return {
            "candidates": db.fetchone("SELECT COUNT(*) AS n FROM candidate")["n"],
            "eval_runs": db.fetchone("SELECT COUNT(*) AS n FROM evaluation_run")["n"],
            "search_state": db.fetchone("SELECT COUNT(*) AS n FROM candidate_search_state")["n"],
        }

    return snapshot


class TestObserverWritesEvidenceOnly:
    def test_writes_evidence_without_touching_search_state(
        self, db, artifact_store, search_state_snapshot
    ):
        experiment_id = "exp-observer"
        _make_candidate(
            db,
            artifact_store,
            candidate_id="parent-1",
            experiment_id=experiment_id,
            task_id="sort",
            code="def f(x): return sorted(x)",
        )
        _make_eval_run(db, candidate_id="parent-1", experiment_id=experiment_id, score=0.5)
        _make_candidate(
            db,
            artifact_store,
            candidate_id="child-1",
            experiment_id=experiment_id,
            task_id="sort",
            code="def f(x): return sorted(set(x))",
        )
        _make_eval_run(db, candidate_id="child-1", experiment_id=experiment_id, score=0.9)

        before = search_state_snapshot()
        observer = _observer(db, artifact_store)
        output = EvalOutput(
            score=0.9,
            metrics={"evaluation_early_stopped": False},
            passed=True,
        )
        evidence = observer.observe(
            candidate_id="child-1",
            peer_id="parent-1",
            code_text="def f(x): return sorted(set(x))",
            output=output,
            execution_summary={"execution_time_ms": 12.0, "memory_peak_kb": 100},
            thought_summary="try dedupe then sort",
            mechanism_tags=["algo"],
            generation=1,
            island_id="island-1",
            task_name="sort",
            experiment_id=experiment_id,
            evaluator_version_id="eval-v1",
            environment_version_id="env-v1",
            db=db,
            artifact_store=artifact_store,
        )
        assert evidence is not None
        assert evidence.status == "completed"

        # 证据表与 artifact 增加。
        assert db.fetchone("SELECT COUNT(*) AS n FROM verification_batch")["n"] == 1
        assert db.fetchone("SELECT COUNT(*) AS n FROM verification_comparison")["n"] == 1
        # 搜索状态不变。
        after = search_state_snapshot()
        assert after == before

    def test_evidence_contains_peer_and_candidate_summary(self, db, artifact_store):
        experiment_id = "exp-observer-2"
        _make_candidate(
            db,
            artifact_store,
            candidate_id="parent-1",
            experiment_id=experiment_id,
            task_id="sort",
            code="parent code body",
        )
        _make_eval_run(db, candidate_id="parent-1", experiment_id=experiment_id, score=0.5)
        _make_candidate(
            db,
            artifact_store,
            candidate_id="child-1",
            experiment_id=experiment_id,
            task_id="sort",
            code="child code body",
        )
        _make_eval_run(db, candidate_id="child-1", experiment_id=experiment_id, score=0.9)

        observer = _observer(db, artifact_store)
        observer.observe(
            candidate_id="child-1",
            peer_id="parent-1",
            code_text="child code body",
            output=EvalOutput(score=0.9, metrics={}, passed=True),
            execution_summary={},
            thought_summary="",
            mechanism_tags=[],
            generation=1,
            island_id="island-1",
            task_name="sort",
            experiment_id=experiment_id,
            evaluator_version_id="eval-v1",
            environment_version_id="env-v1",
            db=db,
            artifact_store=artifact_store,
        )
        comparison = db.fetchone("SELECT * FROM verification_comparison")
        payload = json.loads(artifact_store.load_text(comparison["evidence_hash"]))
        evidence = payload["evidence"]
        assert comparison["left_candidate_id"] == "child-1"
        assert comparison["right_candidate_id"] == "parent-1"
        # 规范化证据包含 preference 与 criterion scores。
        assert "preference_probability" in evidence
        assert set(evidence["criterion_scores"]) == set(CRITERIA)

    def test_hidden_data_not_in_evidence(self, db, artifact_store):
        """证据只含公开摘要；隐藏测试内容不得进入 ArtifactStore."""
        experiment_id = "exp-observer-3"
        _make_candidate(
            db,
            artifact_store,
            candidate_id="parent-1",
            experiment_id=experiment_id,
            task_id="sort",
            code="parent code",
        )
        _make_eval_run(db, candidate_id="parent-1", experiment_id=experiment_id, score=0.5)
        _make_candidate(
            db,
            artifact_store,
            candidate_id="child-1",
            experiment_id=experiment_id,
            task_id="sort",
            code="child code",
        )
        _make_eval_run(db, candidate_id="child-1", experiment_id=experiment_id, score=0.9)
        observer = _observer(db, artifact_store)
        observer.observe(
            candidate_id="child-1",
            peer_id="parent-1",
            code_text="child code",
            output=EvalOutput(score=0.9, metrics={}, passed=True),
            execution_summary={},
            thought_summary="",
            mechanism_tags=[],
            generation=1,
            island_id="island-1",
            task_name="sort",
            experiment_id=experiment_id,
            evaluator_version_id="eval-v1",
            environment_version_id="env-v1",
            db=db,
            artifact_store=artifact_store,
        )
        comparison = db.fetchone("SELECT * FROM verification_comparison")
        stored = artifact_store.load_text(comparison["evidence_hash"])
        assert "hidden" not in stored.lower()
        assert "password" not in stored.lower()


class TestObserverGating:
    def test_skips_when_no_peer(self, db, artifact_store):
        experiment_id = "exp-observer-4"
        _make_candidate(
            db,
            artifact_store,
            candidate_id="child-1",
            experiment_id=experiment_id,
            task_id="sort",
            code="code",
        )
        _make_eval_run(db, candidate_id="child-1", experiment_id=experiment_id, score=0.9)
        observer = _observer(db, artifact_store)
        # peer_id 不存在 → 加载 peer 数据失败 → 返回 None 且不写库。
        result = observer.observe(
            candidate_id="child-1",
            peer_id="missing-peer",
            code_text="code",
            output=EvalOutput(score=0.9, metrics={}, passed=True),
            execution_summary={},
            thought_summary="",
            mechanism_tags=[],
            generation=1,
            island_id="island-1",
            task_name="sort",
            experiment_id=experiment_id,
            evaluator_version_id="eval-v1",
            environment_version_id="env-v1",
            db=db,
            artifact_store=artifact_store,
        )
        assert result is None
        assert db.fetchone("SELECT COUNT(*) AS n FROM verification_batch")["n"] == 0

    def test_failures_do_not_block_observer(self, db, artifact_store):
        """observer 失败只记录，不抛错、不写假证据（§13）."""
        experiment_id = "exp-observer-5"
        _make_candidate(
            db,
            artifact_store,
            candidate_id="parent-1",
            experiment_id=experiment_id,
            task_id="sort",
            code="parent",
        )
        _make_eval_run(db, candidate_id="parent-1", experiment_id=experiment_id, score=0.5)
        _make_candidate(
            db,
            artifact_store,
            candidate_id="child-1",
            experiment_id=experiment_id,
            task_id="sort",
            code="child",
        )
        _make_eval_run(db, candidate_id="child-1", experiment_id=experiment_id, score=0.9)
        # 强制 verifier 返回 unsupported（普通运行语义：记录并回退）。
        service = VerificationService(
            db,
            artifact_store,
            model="verifier-model",
            prompt_version_id="v1",
            granularity=5,
            repetitions=2,
            criteria=CRITERIA,
            order_seed=42,
            mode="observer",
            fail_closed=False,
        )
        observer = VerifierObserver(
            service,
            FakeProbabilisticVerifier(force_status="unsupported"),
            criteria=CRITERIA,
            granularity=5,
            repetitions=2,
            order_seed=42,
        )
        evidence = observer.observe(
            candidate_id="child-1",
            peer_id="parent-1",
            code_text="child",
            output=EvalOutput(score=0.9, metrics={}, passed=True),
            execution_summary={},
            thought_summary="",
            mechanism_tags=[],
            generation=1,
            island_id="island-1",
            task_name="sort",
            experiment_id=experiment_id,
            evaluator_version_id="eval-v1",
            environment_version_id="env-v1",
            db=db,
            artifact_store=artifact_store,
        )
        # 返回 unsupported evidence（不冒充成功），不抛错。
        assert evidence.status == "unsupported"
        batch = db.fetchone("SELECT * FROM verification_batch")
        assert batch["status"] == "failed"
        assert batch["failure_category"] == "unsupported"
