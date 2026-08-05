"""3.1 确定性去重测试：同 artifact_hash 复用已完成评估，跳过 sandbox.

改进计划 §3.1 — 确定性去重 + 渐进评估（渐进部分 EvaluationService 已实现，
本测试覆盖框架侧去重复用路径）。
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from omnievolve.engine.fast_loop import FastLoopStep

pytestmark = pytest.mark.unit


class _EngineStub:
    """FastLoopStep._reuse_duplicate_eval 所需的最小 engine 代理."""

    def __init__(self, row=None, *, dedup_enabled=True, seed=42):
        self._config = SimpleNamespace(dedup_reuse_enabled=dedup_enabled, seed=seed)
        self._experiment_id = "exp-1"
        self._evaluator_version_id = "eval-v2.1.0"
        self._environment_version_id = "env-1"
        self._db = SimpleNamespace(fetchone=lambda *args, **kw: row)
        self._artifact_store = SimpleNamespace(load_text=lambda h: "Traceback: boom" if h else "")
        # 3.1/P1: 去重命中时应为新候选持久化 completed run
        self._eval_repo = _EvalRepoStub()


class _EvalRepoStub:
    """记录 create/start/complete 调用（Codex P1-2 验证）."""

    def __init__(self):
        self.created = []
        self.completed = []

    def create(self, **kwargs):
        run = SimpleNamespace(id=f"run-{len(self.created)}")
        self.created.append(kwargs)
        return run

    def start(self, run_id):
        return True

    def complete(self, run_id, **kwargs):
        self.completed.append(kwargs)
        return True


class TestDedupReuse:
    def _step(self, engine):
        return FastLoopStep(engine)

    def test_miss_returns_none(self):
        step = self._step(_EngineStub(row=None))
        assert step._reuse_duplicate_eval("cand-2", "hash-x") is None

    def test_disabled_skips_lookup(self):
        engine = _EngineStub(row={"candidate_id": "cand-1"}, dedup_enabled=False)
        step = self._step(engine)
        assert step._reuse_duplicate_eval("cand-2", "hash-x") is None
        # 关闭时不应发起 DB 查询（fetchone 被替换为抛错可验证）
        engine._db = SimpleNamespace(
            fetchone=lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not query"))
        )
        assert step._reuse_duplicate_eval("cand-2", "hash-x") is None

    def test_lookup_scoped_to_current_eval_context(self):
        """Codex P1-1：去重必须限定当前 evaluator/environment/seed，避免复用旧上下文分数."""
        captured: dict = {}

        def fake_fetchone(sql, params):
            captured["sql"] = sql
            captured["params"] = params
            return None

        engine = _EngineStub(row=None)
        engine._db = SimpleNamespace(fetchone=fake_fetchone)
        step = self._step(engine)
        step._reuse_duplicate_eval("cand-2", "hash-x")

        assert "r.evaluator_version_id = ?" in captured["sql"]
        assert captured["params"][3:] == ("eval-v2.1.0", "env-1", 42)

    def test_hit_reuses_eval_output(self):
        row = {
            "candidate_id": "cand-1",
            "passed": 1,
            "primary_score": 0.75,
            "metrics": json.dumps({"task_score": 0.75, "benchmark_median": 0.7}),
            "stderr_hash": "stderr-artifact",
            "stdout_hash": "stdout-artifact",
            "execution_time_ms": 123.0,
            "memory_peak_kb": 456,
            "cpu_time_ms": 100.0,
        }
        engine = _EngineStub(row=row)
        step = self._step(engine)
        output = step._reuse_duplicate_eval("cand-2", "hash-x")

        assert output is not None
        assert output.score == pytest.approx(0.75)
        assert output.passed is True
        assert "boom" in output.failure_reason  # 从 stderr artifact 读取
        # 审计标记
        assert output.metrics["dedup_reused"] is True
        assert output.metrics["dedup_source_candidate"] == "cand-1"
        assert output.metrics["task_score"] == 0.75
        # Codex P1-2：去重候选持久化 completed run（分数可被后续查询）
        assert len(engine._eval_repo.created) == 1
        assert engine._eval_repo.created[0]["candidate_id"] == "cand-2"
        assert len(engine._eval_repo.completed) == 1
        assert engine._eval_repo.completed[0]["primary_score"] == pytest.approx(0.75)
        assert engine._eval_repo.completed[0]["metrics"]["dedup_reused"] is True
        assert engine._eval_repo.completed[0]["execution_time_ms"] == 123.0
        assert engine._eval_repo.completed[0]["stdout_hash"] == "stdout-artifact"

    def test_hit_failed_candidate_reuses_failure(self):
        row = {
            "candidate_id": "cand-1",
            "passed": 0,
            "primary_score": 0.0,
            "metrics": json.dumps({"task_score": 0.0}),
            "stderr_hash": None,
        }
        step = self._step(_EngineStub(row=row))
        output = step._reuse_duplicate_eval("cand-2", "hash-x")
        assert output is not None
        assert output.passed is False
        assert output.score == 0.0
