"""VerificationService 持久化与失败语义测试（集成计划 §8/§13/§16.4）."""

from __future__ import annotations

from typing import Any

import pytest

from omnievolve.eval.fake_verifier import FakeProbabilisticVerifier
from omnievolve.eval.verification_service import VerificationService
from omnievolve.eval.verifier import (
    VerificationRequest,
    VerificationStatus,
)
from omnievolve.exceptions import LLMError, LLMVerifierCapabilityError

CRITERIA = ("specification_fidelity", "mechanism_realization", "evidence_consistency")


@pytest.fixture(autouse=True)
def _seed_fk_rows(db):
    """FK：experiment + candidate 行（comparison 引用两者）. """
    db.execute(
        """
        INSERT OR IGNORE INTO experiment
            (id, task_id, task_name, status, config_snapshot)
        VALUES ('exp-1', 'sort', 'sort', 'created', '{}')
        """
    )
    db.execute(
        """
        INSERT OR IGNORE INTO artifact
            (hash, artifact_type, byte_size, relative_path)
        VALUES ('hash', 'source', 1, 'x')
        """
    )
    for candidate_id in (
        "cand-0", "cand-1", "cand-2", "cand-3", "cand-4",
        "peer-0", "peer-1", "peer-2", "peer-3", "peer-4",
    ):
        db.execute(
            """
            INSERT OR IGNORE INTO candidate
                (id, experiment_id, task_id, generation, artifact_hash,
                 search_policy_id, status)
            VALUES (?, 'exp-1', 'sort', 1, 'hash', 'policy-1', 'evaluated')
            """,
            (candidate_id,),
        )
    yield


def _request(candidate_id="cand-1", peer_id="cand-2", seed=7, **overrides):
    evidence = {
        "task_description": "sort integers",
        "candidate_summary": "def f(x): return sorted(x)",
        "candidate_diff": "",
        "candidate_eval": '{"passed": true, "score": 0.9}',
        "peer_summary": "def f(x): return x",
        "peer_diff": "",
        "peer_eval": '{"passed": true, "score": 0.5}',
    }
    evidence.update(overrides.pop("evidence", {}))
    return VerificationRequest(
        experiment_id=overrides.pop("experiment_id", "exp-1"),
        candidate_id=candidate_id,
        peer_candidate_id=peer_id,
        task_id="sort",
        criteria=CRITERIA,
        granularity=5,
        repetitions=2,
        order_seed=seed,
        evidence=evidence,
    )


def _service(db, artifact_store, **overrides):
    params: dict[str, Any] = {
        "model": "verifier-model",
        "prompt_version_id": "verifier-observer-v1",
        "granularity": 5,
        "repetitions": 2,
        "criteria": CRITERIA,
        "order_seed": 7,
    }
    params.update(overrides)
    return VerificationService(db, artifact_store, **params)


class TestPersistence:
    def test_writes_batch_and_comparison(self, db, artifact_store):
        service = _service(db, artifact_store)
        verifier = FakeProbabilisticVerifier()
        evidence = service.verify_pair(_request(), verifier)

        assert evidence.status == VerificationStatus.COMPLETED
        batch = db.fetchone("SELECT * FROM verification_batch")
        assert batch is not None
        assert batch["mode"] == "observer"
        assert batch["model"] == "verifier-model"
        assert batch["granularity"] == 5
        assert batch["repetitions"] == 2
        assert batch["status"] == "completed"

        comparison = db.fetchone("SELECT * FROM verification_comparison")
        assert comparison is not None
        assert comparison["left_candidate_id"] == "cand-1"
        assert comparison["right_candidate_id"] == "cand-2"
        assert comparison["status"] == "completed"
        assert comparison["evidence_hash"]

    def test_evidence_stored_in_artifact_store(self, db, artifact_store):
        service = _service(db, artifact_store)
        evidence = service.verify_pair(_request(), FakeProbabilisticVerifier())
        comparison = db.fetchone("SELECT evidence_hash FROM verification_comparison")
        assert artifact_store.exists(comparison["evidence_hash"])
        stored = artifact_store.load_text(comparison["evidence_hash"])
        assert "evidence" in stored
        assert evidence.status in stored

    def test_second_pair_creates_separate_batch(self, db, artifact_store):
        service = _service(db, artifact_store)
        verifier = FakeProbabilisticVerifier()
        service.verify_pair(_request(candidate_id="cand-1", peer_id="cand-2"), verifier)
        service.verify_pair(_request(candidate_id="cand-3", peer_id="cand-4"), verifier)
        assert db.fetchone("SELECT COUNT(*) AS n FROM verification_batch")["n"] == 2
        assert db.fetchone("SELECT COUNT(*) AS n FROM verification_comparison")["n"] == 2


class TestIdempotency:
    def test_same_request_hash_reuses_evidence(self, db, artifact_store):
        service = _service(db, artifact_store)
        verifier = FakeProbabilisticVerifier()
        request = _request()
        first = service.verify_pair(request, verifier)
        call_count = len(verifier.calls)
        second = service.verify_pair(request, verifier)
        # 不重复调用 provider。
        assert len(verifier.calls) == call_count
        assert second.evidence_hash == first.evidence_hash
        assert db.fetchone("SELECT COUNT(*) AS n FROM verification_comparison")["n"] == 1

    def test_resume_invariant(self, db, artifact_store):
        """run(N) == run(K) + resume(N-K)（§15 Fake verifier 不变式）."""
        requests = [_request(candidate_id=f"cand-{i}", peer_id=f"peer-{i}", seed=i) for i in range(4)]
        verifier = FakeProbabilisticVerifier()
        full_service = _service(db, artifact_store)
        full_results = [
            full_service.verify_pair(request, verifier) for request in requests
        ]
        full_calls = len(verifier.calls)

        # 全新 service（模拟 resume）逐 request 重放：全部命中幂等缓存。
        resumed_service = _service(db, artifact_store)
        resumed_results = [
            resumed_service.verify_pair(request, verifier) for request in requests
        ]
        assert len(verifier.calls) == full_calls  # resume 不重复调用 provider
        for full, resumed in zip(full_results, resumed_results):
            assert full.evidence_hash == resumed.evidence_hash
            assert full.preference_probability == resumed.preference_probability
            assert full.criterion_scores == resumed.criterion_scores

    def test_deterministic_fake_verifier_repeatable(self):
        request = _request()
        first = FakeProbabilisticVerifier().verify_pair(request)
        second = FakeProbabilisticVerifier().verify_pair(request)
        assert first.evidence_hash == second.evidence_hash
        assert first.preference_probability == second.preference_probability

    def test_hash_includes_service_provenance(self, db, artifact_store):
        """换 model/prompt/capability 后不得复用旧 evidence（§8 幂等键）."""
        request = _request()
        verifier = FakeProbabilisticVerifier()

        first_service = _service(db, artifact_store, model="verifier-model-a")
        first_service.verify_pair(request, verifier)
        first_rows = db.fetchall("SELECT request_hash FROM verification_comparison")
        assert len(first_rows) == 1
        first_hash = first_rows[0]["request_hash"]

        # 同一 request、不同 model → 新 request_hash → 重新执行 provider。
        second_service = _service(db, artifact_store, model="verifier-model-b")
        second_service.verify_pair(request, verifier)
        rows = db.fetchall("SELECT request_hash FROM verification_comparison")
        assert len(rows) == 2
        assert rows[1]["request_hash"] != first_hash
        assert len(verifier.calls) == 2

        # 同一 request、不同 capability_hash → 同样不复用。
        third_service = _service(
            db, artifact_store, model="verifier-model-a", capability_hash="new-cap"
        )
        third_service.verify_pair(request, verifier)
        assert db.fetchone("SELECT COUNT(*) AS n FROM verification_comparison")["n"] == 3
        assert len(verifier.calls) == 3


class TestFailureSemantics:
    def test_unsupported_records_and_returns_in_ordinary_run(self, db, artifact_store):
        service = _service(db, artifact_store, fail_closed=False)
        verifier = FakeProbabilisticVerifier(force_status=VerificationStatus.UNSUPPORTED)
        evidence = service.verify_pair(_request(), verifier)
        assert evidence.status == VerificationStatus.UNSUPPORTED
        batch = db.fetchone("SELECT * FROM verification_batch")
        assert batch["status"] == "failed"
        assert batch["failure_category"] == "unsupported"

    def test_unsupported_fails_closed_in_research_run(self, db, artifact_store):
        service = _service(db, artifact_store, fail_closed=True)
        verifier = FakeProbabilisticVerifier(force_status=VerificationStatus.UNSUPPORTED)
        with pytest.raises(LLMVerifierCapabilityError, match="fail closed"):
            service.verify_pair(_request(), verifier)

    def test_cached_failure_still_fails_closed_on_resume(self, db, artifact_store):
        """resume 命中缓存失败证据时不得绕过 fail-closed（§13）."""
        service = _service(db, artifact_store, fail_closed=True)
        verifier = FakeProbabilisticVerifier(force_status=VerificationStatus.UNSUPPORTED)
        with pytest.raises(LLMVerifierCapabilityError, match="fail closed"):
            service.verify_pair(_request(), verifier)
        # 第二次调用（模拟 resume）命中缓存：必须仍然抛错，且不重复调用 provider。
        with pytest.raises(LLMVerifierCapabilityError, match="fail closed"):
            service.verify_pair(_request(), verifier)
        assert len(verifier.calls) == 1

    def test_cached_failure_falls_back_in_ordinary_run(self, db, artifact_store):
        """普通运行：缓存失败证据回退，不重复调用 provider、不伪装成功."""
        service = _service(db, artifact_store, fail_closed=False)
        verifier = FakeProbabilisticVerifier(force_status=VerificationStatus.UNSUPPORTED)
        first = service.verify_pair(_request(), verifier)
        assert first.status == VerificationStatus.UNSUPPORTED
        second = service.verify_pair(_request(), verifier)
        assert second.status == VerificationStatus.UNSUPPORTED
        assert len(verifier.calls) == 1
        assert db.fetchone("SELECT COUNT(*) AS n FROM verification_comparison")["n"] == 1

    def test_incomplete_evidence_fails_closed_in_research_run(self, db, artifact_store):
        service = _service(db, artifact_store, fail_closed=True)
        verifier = FakeProbabilisticVerifier(force_status=VerificationStatus.INCOMPLETE_EVIDENCE)
        with pytest.raises(LLMError, match="fail closed"):
            service.verify_pair(_request(), verifier)

    def test_fake_verifier_coverage_param_effective(self):
        """coverage 参数真正进入证据与状态（可测 low-coverage 分支）."""
        evidence = FakeProbabilisticVerifier(coverage=0.2).verify_pair(_request())
        assert evidence.probability_coverage == 0.2
        assert evidence.status == VerificationStatus.INSUFFICIENT_COVERAGE

    def test_low_coverage_fails_closed_in_research_run(self, db, artifact_store):
        service = _service(db, artifact_store, fail_closed=True)
        verifier = FakeProbabilisticVerifier(coverage=0.2)
        with pytest.raises(LLMError, match="fail closed"):
            service.verify_pair(_request(), verifier)
        batch = db.fetchone("SELECT * FROM verification_batch")
        assert batch["status"] == "failed"

    def test_invalid_request_records_failed(self, db, artifact_store):
        service = _service(db, artifact_store, fail_closed=False)
        # 缺失证据字段 → verifier 抛 ValueError → service 记录 failed。
        request = VerificationRequest(
            experiment_id="exp-1",
            candidate_id="cand-1",
            peer_candidate_id="cand-2",
            task_id="sort",
            criteria=CRITERIA,
            granularity=5,
            repetitions=2,
            order_seed=7,
            evidence={"task_description": "only"},
        )
        evidence = service.verify_pair(request, FakeProbabilisticVerifier())
        assert evidence.status == VerificationStatus.FAILED
        comparison = db.fetchone("SELECT * FROM verification_comparison")
        assert comparison["status"] == VerificationStatus.FAILED

    def test_unknown_cost_kept_null(self, db, artifact_store):
        service = _service(db, artifact_store)
        service.verify_pair(_request(), FakeProbabilisticVerifier())
        batch = db.fetchone("SELECT cost_usd, cost_known FROM verification_batch")
        assert batch["cost_usd"] is None
        # unknown cost 必须如实标记为未知（§8 契约），不得伪装成成本已知。
        assert batch["cost_known"] == 0

    def test_batch_records_verifier_usage(self, db, artifact_store):
        """真实 token/成本进入 verification_batch 账本（§8）."""

        class _UsageVerifier(FakeProbabilisticVerifier):
            total_tokens = 137
            cost_usd = 0.0042
            cost_known = True

        service = _service(db, artifact_store)
        service.verify_pair(_request(), _UsageVerifier())
        batch = db.fetchone(
            "SELECT total_tokens, cost_usd, cost_known FROM verification_batch"
        )
        assert batch["total_tokens"] == 137
        assert batch["cost_usd"] == pytest.approx(0.0042)
        assert batch["cost_known"] == 1

    def test_missing_evidence_never_impersonates_default_half(self, db, artifact_store):
        """缺少证据时不得写默认 0.5 并当作成功."""
        service = _service(db, artifact_store)
        request = VerificationRequest(
            experiment_id="exp-1",
            candidate_id="cand-1",
            peer_candidate_id="cand-2",
            task_id="sort",
            criteria=CRITERIA,
            granularity=5,
            repetitions=2,
            order_seed=7,
            evidence={},
        )
        evidence = service.verify_pair(request, FakeProbabilisticVerifier())
        assert evidence.status != VerificationStatus.COMPLETED


class TestQuery:
    def test_find_comparison_by_pair(self, db, artifact_store):
        service = _service(db, artifact_store)
        service.verify_pair(_request(), FakeProbabilisticVerifier())
        rows = service.find_comparison(candidate_id="cand-1", peer_candidate_id="cand-2")
        assert len(rows) == 1
        # 方向无关查询。
        reversed_rows = service.find_comparison(candidate_id="cand-2", peer_candidate_id="cand-1")
        assert len(reversed_rows) == 1

    def test_batches_for_experiment(self, db, artifact_store):
        service = _service(db, artifact_store)
        service.verify_pair(_request(), FakeProbabilisticVerifier())
        batches = service.batches_for_experiment("exp-1")
        assert len(batches) == 1
        assert batches[0].mode == "observer"
