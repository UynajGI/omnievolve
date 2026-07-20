"""OpenTelemetry 可观测性测试 — 验证降级路径和指标记录."""

from __future__ import annotations

from omnievolve.eval.observability import (
    record_candidate_generated,
    record_checkpoint_saved,
    record_counter,
    record_evaluation_completed,
    record_gauge,
    record_slow_loop_triggered,
    traced_block,
)


class TestObservabilityDegradation:
    """未安装 opentelemetry 时所有函数应不抛异常（优雅降级）."""

    def test_record_gauge_noop(self):
        """record_gauge 在无 OTEL 时不抛异常."""
        record_gauge("test.metric", 1.0, label="v")

    def test_record_counter_noop(self):
        record_counter("test.counter", delta=5, role="director")

    def test_record_candidate_noop(self):
        record_candidate_generated(1, "island_0", "gpt-4")

    def test_record_evaluation_noop(self):
        record_evaluation_completed(0.95, True, 150.0)

    def test_record_slow_loop_noop(self):
        record_slow_loop_triggered(10, "WARN")

    def test_record_checkpoint_noop(self):
        record_checkpoint_saved(25, 100)

    def test_traced_block_noop(self):
        """traced_block 上下文管理器在无 OTEL 时正常工作."""
        with traced_block("test.span", node_id="abc"):
            x = 1 + 1
        assert x == 2

    def test_traced_block_returns_value(self):
        """traced_block 正确传播返回值."""
        result = []
        with traced_block("test.block"):
            result.append("inside")
        assert result == ["inside"]
