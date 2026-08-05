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

    def __init__(self, row=None, *, dedup_enabled=True):
        self._config = SimpleNamespace(dedup_reuse_enabled=dedup_enabled)
        self._experiment_id = "exp-1"
        self._db = SimpleNamespace(fetchone=lambda *args, **kw: row)
        self._artifact_store = SimpleNamespace(load_text=lambda h: "Traceback: boom" if h else "")


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

    def test_hit_reuses_eval_output(self):
        row = {
            "candidate_id": "cand-1",
            "passed": 1,
            "primary_score": 0.75,
            "metrics": json.dumps({"task_score": 0.75, "benchmark_median": 0.7}),
            "stderr_hash": "stderr-artifact",
        }
        step = self._step(_EngineStub(row=row))
        output, eval_run, job, sandbox_result = step._reuse_duplicate_eval("cand-2", "hash-x")

        assert output is not None
        assert output.score == pytest.approx(0.75)
        assert output.passed is True
        assert "boom" in output.failure_reason  # 从 stderr artifact 读取
        # 审计标记
        assert output.metrics["dedup_reused"] is True
        assert output.metrics["dedup_source_candidate"] == "cand-1"
        assert output.metrics["task_score"] == 0.75
        # 跳过 sandbox：无 eval_run / job / outcome
        assert eval_run is None and job is None and sandbox_result is None

    def test_hit_failed_candidate_reuses_failure(self):
        row = {
            "candidate_id": "cand-1",
            "passed": 0,
            "primary_score": 0.0,
            "metrics": json.dumps({"task_score": 0.0}),
            "stderr_hash": None,
        }
        step = self._step(_EngineStub(row=row))
        output, _, _, _ = step._reuse_duplicate_eval("cand-2", "hash-x")
        assert output is not None
        assert output.passed is False
        assert output.score == 0.0
