"""R1 离线 replay calibration runner 测试（集成计划 §17.2）."""

from __future__ import annotations

import json

import pytest

from omnievolve.eval.fake_verifier import FakeProbabilisticVerifier
from omnievolve.eval.verifier import VerificationStatus
from omnievolve.research.verifier_replay import (
    VariantReport,
    VerifierReplayRunner,
    VerifierVariant,
    assess_r1_gate,
    write_report,
)


def _seed_candidates(db, artifact_store, experiment_id="exp-replay"):
    """构造两个 task 的 candidates + completed evaluation_runs."""
    db.execute(
        """
        INSERT OR IGNORE INTO experiment
            (id, task_id, task_name, status, config_snapshot)
        VALUES (?, 'task', 'task', 'created', '{}')
        """,
        (experiment_id,),
    )
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
    for task, candidates in {
        "sort": [("c-sort-1", 0.90), ("c-sort-2", 0.45), ("c-sort-3", 0.20)],
        "nqueens": [("c-nq-1", 0.80), ("c-nq-2", 0.30)],
    }.items():
        for candidate_id, score in candidates:
            artifact_hash = artifact_store.store_text(
                f"# {candidate_id}\ndef solve(): pass", "source"
            )
            db.execute(
                """
                INSERT INTO candidate
                    (id, experiment_id, task_id, generation, island_id,
                     artifact_hash, search_policy_id, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    candidate_id,
                    experiment_id,
                    task,
                    1,
                    "island-1",
                    artifact_hash,
                    "policy-1",
                    "evaluated",
                ),
            )
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
                    1,
                    score,
                    json.dumps({}),
                    10.0,
                    "2026-08-01T00:00:00Z",
                ),
            )


def _runner(db, artifact_store, *, verifier_factory=None, seed=0):
    if verifier_factory is None:

        def factory(variant):
            del variant
            return FakeProbabilisticVerifier(seed=seed)
    else:
        factory = verifier_factory
    return VerifierReplayRunner(db, artifact_store, verifier_factory=factory)


class TestBuildLabeledPairs:
    def test_pairs_respect_min_score_gap(self, db, artifact_store):
        _seed_candidates(db, artifact_store)
        runner = _runner(db, artifact_store)
        pairs = runner.build_labeled_pairs(experiment_id="exp-replay", min_score_gap=0.05)
        assert len(pairs) >= 4
        for pair in pairs:
            assert abs(pair.candidate_score - pair.peer_score) >= 0.05
            assert pair.label in (1.0, -1.0)
            assert pair.label == (1.0 if pair.candidate_score > pair.peer_score else -1.0)
            assert "candidate_summary" in pair.evidence
            assert "peer_eval" in pair.evidence

    def test_high_gap_excludes_noisy_pairs(self, db, artifact_store):
        _seed_candidates(db, artifact_store)
        runner = _runner(db, artifact_store)
        pairs = runner.build_labeled_pairs(experiment_id="exp-replay", min_score_gap=0.5)
        for pair in pairs:
            assert abs(pair.candidate_score - pair.peer_score) >= 0.5
        # sort: 0.9-0.45=0.45 (<0.5 排除), 0.9-0.2=0.7, 0.45-0.2=0.25 排除
        # nqueens: 0.8-0.3=0.5
        assert len(pairs) == 2

    def test_task_filter(self, db, artifact_store):
        _seed_candidates(db, artifact_store)
        runner = _runner(db, artifact_store)
        pairs = runner.build_labeled_pairs(task_id="nqueens", min_score_gap=0.05)
        assert pairs
        assert all(pair.task_id == "nqueens" for pair in pairs)


class TestRunVariant:
    def test_report_shape(self, db, artifact_store):
        _seed_candidates(db, artifact_store)
        runner = _runner(db, artifact_store)
        pairs = runner.build_labeled_pairs(experiment_id="exp-replay", min_score_gap=0.05)
        variant = VerifierVariant(
            name="G5_K1_C3", granularity=5, repetitions=1, criteria=("specification_fidelity",)
        )
        report = runner.run_variant(pairs, variant)
        assert isinstance(report, VariantReport)
        assert report.pairs_attempted == len(pairs)
        assert report.pairs_completed == len(pairs)
        assert 0.0 <= report.accuracy <= 1.0
        assert 0.0 <= report.brier <= 1.0
        assert report.accuracy_ci_lower <= report.accuracy
        assert report.failure_rate == 0.0

    def test_fixture_verifier_perfect_accuracy(self, db, artifact_store):
        """fixture 按 label 设置偏好 → accuracy 1.0，gate 通过."""
        _seed_candidates(db, artifact_store)
        runner = _runner(db, artifact_store, seed=1)
        pairs = runner.build_labeled_pairs(experiment_id="exp-replay", min_score_gap=0.1)
        fixture = {
            (pair.candidate_id, pair.peer_candidate_id): (
                (0.9, 0.1) if pair.label > 0 else (0.1, 0.9)
            )
            for pair in pairs
        }
        fixture_runner = VerifierReplayRunner(
            db,
            artifact_store,
            verifier_factory=lambda variant: FakeProbabilisticVerifier(  # noqa: E731
                fixture=fixture, seed=1
            ),
        )
        report = fixture_runner.run_variant(
            pairs,
            VerifierVariant("perfect", 5, 1, ("specification_fidelity",)),
        )
        assert report.accuracy == pytest.approx(1.0)

    def test_failures_counted(self, db, artifact_store):
        _seed_candidates(db, artifact_store)
        runner = _runner(db, artifact_store)
        pairs = runner.build_labeled_pairs(experiment_id="exp-replay", min_score_gap=0.05)

        def failing_factory(variant):
            del variant
            return FakeProbabilisticVerifier(
                force_status=VerificationStatus.INSUFFICIENT_COVERAGE, seed=3
            )

        failing_runner = VerifierReplayRunner(db, artifact_store, verifier_factory=failing_factory)
        report = failing_runner.run_variant(
            pairs,
            VerifierVariant("G1_K1_C1", 1, 1, ("specification_fidelity",)),
        )
        assert report.pairs_completed == 0
        assert report.failure_rate == 1.0
        assert report.failure_categories.get("insufficient_coverage", 0) == len(pairs)

    def test_calibration_matrix_runs_all_variants(self, db, artifact_store):
        _seed_candidates(db, artifact_store)
        runner = _runner(db, artifact_store)
        pairs = runner.build_labeled_pairs(experiment_id="exp-replay", min_score_gap=0.05)
        reports = runner.run_calibration(
            pairs,
            granularities=(1, 5),
            repetitions=(1,),
            criteria_options=(("specification_fidelity",),),
        )
        assert len(reports) == 2
        assert {report.name for report in reports} == {"G1_K1_C1", "G5_K1_C1"}


class TestR1Gate:
    def test_gate_rejects_random_verifier(self, db, artifact_store):
        """随机偏好 verifier → CI 下界无法 > 0.5，gate 不通过."""
        _seed_candidates(db, artifact_store)
        runner = _runner(db, artifact_store)
        pairs = runner.build_labeled_pairs(experiment_id="exp-replay", min_score_gap=0.05)
        report = runner.run_variant(
            pairs,
            VerifierVariant("random", 5, 1, ("specification_fidelity",)),
        )
        gate = assess_r1_gate(report)
        assert not gate.passed
        assert any("accuracy" in reason for reason in gate.reasons)

    def test_gate_accepts_perfect_verifier_with_known_cost(self):
        report = VariantReport(
            name="perfect",
            granularity=5,
            repetitions=1,
            criteria=("specification_fidelity",),
            pairs_attempted=50,
            pairs_completed=50,
            accuracy=0.95,
            accuracy_ci_lower=0.90,
            brier=0.05,
            ece=0.03,
            tie_rate=0.0,
            spearman=0.8,
            probability_coverage=0.99,
            failure_rate=0.0,
            failure_categories={},
            total_tokens=1000,
            cost_usd=0.01,
            cost_known=True,
        )
        gate = assess_r1_gate(report)
        assert gate.passed

    def test_gate_rejects_unknown_cost(self):
        report = VariantReport(
            name="x",
            granularity=1,
            repetitions=1,
            criteria=("specification_fidelity",),
            pairs_attempted=40,
            pairs_completed=40,
            accuracy=0.95,
            accuracy_ci_lower=0.90,
            brier=0.05,
            ece=0.03,
            tie_rate=0.0,
            spearman=0.8,
            probability_coverage=0.99,
            failure_rate=0.0,
            failure_categories={},
            total_tokens=10,
            cost_usd=None,
            cost_known=False,
        )
        assert not assess_r1_gate(report).passed
        # 协议预先排除成本时允许通过。
        assert assess_r1_gate(report, cost_excluded=True).passed


class TestDataIntegrity:
    """数据构造完整性：无泄漏、无重复样本、统计门小样本保护."""

    def test_evidence_does_not_leak_ground_truth_scores(self, db, artifact_store):
        """ground-truth 分数不得进入 prompt（§17.2 防 target leakage）."""
        _seed_candidates(db, artifact_store)
        runner = _runner(db, artifact_store)
        pairs = runner.build_labeled_pairs(experiment_id="exp-replay", min_score_gap=0.05)
        assert pairs
        for pair in pairs:
            candidate_eval = json.loads(pair.evidence["candidate_eval"])
            peer_eval = json.loads(pair.evidence["peer_eval"])
            assert "score" not in candidate_eval
            assert "score" not in peer_eval
            assert candidate_eval["passed"] is True
            assert peer_eval["passed"] is True

    def test_latest_run_only_per_candidate(self, db, artifact_store):
        """同候选多 evaluation_run（seed/attempt）不重复成 pair、不混语义."""
        _seed_candidates(db, artifact_store)
        # 给 c-sort-1 / c-sort-2 各加一条 latest run（不同分数/seed）。
        db.execute(
            """
            INSERT INTO evaluation_run
                (id, experiment_id, candidate_id, evaluator_version_id,
                 environment_version_id, seed, split_name, attempt, status,
                 passed, primary_score, metrics, execution_time_ms, finished_at)
            VALUES ('run-c-sort-1-v2', 'exp-replay', 'c-sort-1', 'eval-v1',
                    'env-v1', 1, 'default', 2, 'completed', 1, 0.50, '{}',
                    10.0, '2026-08-02T00:00:00Z')
            """
        )
        db.execute(
            """
            INSERT INTO evaluation_run
                (id, experiment_id, candidate_id, evaluator_version_id,
                 environment_version_id, seed, split_name, attempt, status,
                 passed, primary_score, metrics, execution_time_ms, finished_at)
            VALUES ('run-c-sort-2-v2', 'exp-replay', 'c-sort-2', 'eval-v1',
                    'env-v1', 1, 'default', 2, 'completed', 1, 0.55, '{}',
                    10.0, '2026-08-02T00:00:00Z')
            """
        )
        runner = _runner(db, artifact_store)
        pairs = runner.build_labeled_pairs(experiment_id="exp-replay", min_score_gap=0.05)
        sort_pairs = [pair for pair in pairs if pair.task_id == "sort"]
        pair_keys = [(pair.candidate_id, pair.peer_candidate_id) for pair in sort_pairs]
        # 每个逻辑 pair 只出现一次（latest run 0.50/0.55 配对）。
        assert len(pair_keys) == len(set(pair_keys))
        assert len(sort_pairs) == 3
        # c-sort-1 使用 latest 0.50（而非 0.90）：与 c-sort-2(0.55) 差 0.05。
        pair_12 = next(
            p
            for p in sort_pairs
            if {"c-sort-1", "c-sort-2"} <= {p.candidate_id, p.peer_candidate_id}
        )
        assert abs(pair_12.candidate_score - pair_12.peer_score) == pytest.approx(0.05)

    def test_abstention_not_counted_as_correct(self, db, artifact_store):
        """恒定输出 0.5 的 verifier：tie 不计为正确（§17.2）."""
        _seed_candidates(db, artifact_store)
        runner = _runner(db, artifact_store)
        pairs = runner.build_labeled_pairs(experiment_id="exp-replay", min_score_gap=0.05)
        fixture = {(pair.candidate_id, pair.peer_candidate_id): (0.5, 0.5) for pair in pairs}
        tie_runner = VerifierReplayRunner(
            db,
            artifact_store,
            verifier_factory=lambda variant: FakeProbabilisticVerifier(  # noqa: E731
                fixture=fixture
            ),
        )
        report = tie_runner.run_variant(
            pairs,
            VerifierVariant("tie", 5, 1, ("specification_fidelity",)),
        )
        assert report.tie_rate == 1.0
        assert report.accuracy == 0.0
        assert report.accuracy_ci_lower == 0.0
        assert not assess_r1_gate(report, cost_excluded=True).passed

    def test_wilson_ci_not_inflated_for_tiny_samples(self):
        from omnievolve.research.verifier_replay import _one_sided_ci_lower

        # Wald 对 (1.0, 1) 返回 ~0.999998；Wilson 必须远低于该值。
        assert _one_sided_ci_lower(1.0, 1) < 0.5
        # n=3 全成功：Wilson 下界 ≈0.526（远低于 Wald 的 ~0.999999），
        # 剩余的小样本放行风险由 assess_r1_gate 的 min_pairs 门槛兜底。
        assert _one_sided_ci_lower(1.0, 3) < 0.8
        assert _one_sided_ci_lower(0.0, 1) == 0.0
        # 样本充足时下界收窄到可放行区间。
        assert _one_sided_ci_lower(1.0, 30) > 0.8
        assert _one_sided_ci_lower(0.95, 100) > 0.5

    def test_gate_requires_minimum_pairs(self):
        """R1 门需要最小有效 pair 数，防止极少证据放行（§17.2）."""
        small = VariantReport(
            name="tiny",
            granularity=5,
            repetitions=1,
            criteria=("specification_fidelity",),
            pairs_attempted=5,
            pairs_completed=5,
            accuracy=1.0,
            accuracy_ci_lower=0.60,
            brier=0.05,
            ece=0.03,
            tie_rate=0.0,
            spearman=0.8,
            probability_coverage=0.99,
            failure_rate=0.0,
            failure_categories={},
            total_tokens=100,
            cost_usd=0.0,
            cost_known=True,
        )
        gate = assess_r1_gate(small, cost_excluded=True)
        assert not gate.passed
        assert any("minimum" in reason for reason in gate.reasons)
        large = VariantReport(
            name="large",
            granularity=5,
            repetitions=1,
            criteria=("specification_fidelity",),
            pairs_attempted=40,
            pairs_completed=40,
            accuracy=0.95,
            accuracy_ci_lower=0.90,
            brier=0.05,
            ece=0.03,
            tie_rate=0.0,
            spearman=0.8,
            probability_coverage=0.99,
            failure_rate=0.0,
            failure_categories={},
            total_tokens=100,
            cost_usd=0.0,
            cost_known=True,
        )
        assert assess_r1_gate(large, cost_excluded=True).passed


class TestReportWriter:
    def test_write_report_json(self, tmp_path):
        report = VariantReport(
            name="G5_K1_C3",
            granularity=5,
            repetitions=1,
            criteria=("specification_fidelity",),
            pairs_attempted=2,
            pairs_completed=2,
            accuracy=0.5,
            accuracy_ci_lower=0.25,
            brier=0.25,
            ece=0.2,
            tie_rate=0.1,
            spearman=None,
            probability_coverage=0.97,
            failure_rate=0.0,
            failure_categories={},
            total_tokens=10,
            cost_usd=0.0,
            cost_known=True,
        )
        path = write_report([report], str(tmp_path / "report.json"))
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
        assert payload["protocol"] == "R1-verifier-replay-calibration"
        assert payload["variants"][0]["name"] == "G5_K1_C3"
