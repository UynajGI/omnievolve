"""OpenTelemetry 可观测性集成 (P2).

基于现有 TelemetryAggregator + Prometheus 导出，添加:
  - 跨度（span）跟踪 Fast Loop 各步骤耗时
  - 指标导出到 OTLP 收集器（可选）
  - 零依赖降级：未安装 opentelemetry 时自动退化

依赖（可选）:
  pip install opentelemetry-api opentelemetry-sdk opentelemetry-exporter-otlp
"""

from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from typing import Any

logger = logging.getLogger(__name__)

# ── 惰性导入：未安装时降级 ──────────────────────────────────────────

_HAS_OTEL = False
_tracer: Any = None
_meter: Any = None


def _ensure_otel() -> None:
    """惰性初始化 OpenTelemetry（如果可用）."""
    global _HAS_OTEL, _tracer, _meter
    if _HAS_OTEL:
        return
    try:
        from opentelemetry import metrics, trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider

        resource = Resource(attributes={"service.name": "omnievolve", "service.version": "0.2.0"})

        provider = TracerProvider(resource=resource)
        trace.set_tracer_provider(provider)

        _tracer = trace.get_tracer("omnievolve.evolution")
        _meter = metrics.get_meter("omnievolve.metrics")

        _HAS_OTEL = True
        logger.info("OpenTelemetry tracing enabled")
    except ImportError:
        logger.debug("OpenTelemetry not installed — tracing disabled")


# ── 公共 API ─────────────────────────────────────────────────────────


def trace_step(step_name: str):
    """装饰器：自动跟踪 Fast Loop 步骤耗时.

    Usage:
        @trace_step("director.evolve_thought")
        def evolve_thought(self, ctx): ...
    """

    def decorator(func):
        def wrapper(*args, **kwargs):
            _ensure_otel()
            if not _HAS_OTEL:
                return func(*args, **kwargs)
            with _tracer.start_as_current_span(step_name) as span:
                start = time.perf_counter()
                result = func(*args, **kwargs)
                span.set_attribute("duration_ms", (time.perf_counter() - start) * 1000)
                return result

        return wrapper

    return decorator


@contextmanager
def traced_block(name: str, **attrs):
    """上下文管理器：跟踪代码块.

    Usage:
        with traced_block("mcts.select", node_id=root):
            parent = self._mcts.select(root)
    """
    _ensure_otel()
    if not _HAS_OTEL:
        yield
        return
    with _tracer.start_as_current_span(name) as span:
        for k, v in attrs.items():
            span.set_attribute(k, v)
        start = time.perf_counter()
        try:
            yield
        finally:
            span.set_attribute("duration_ms", (time.perf_counter() - start) * 1000)


def record_gauge(name: str, value: float, **labels):
    """记录仪表指标（Prometheus 兼容）."""
    _ensure_otel()
    if not _HAS_OTEL:
        return
    gauge = _meter.create_gauge(name, description=f"Auto-created gauge: {name}")
    gauge.set(value, labels)


def record_counter(name: str, delta: int = 1, **labels):
    """记录计数指标."""
    _ensure_otel()
    if not _HAS_OTEL:
        return
    counter = _meter.create_counter(name, description=f"Auto-created counter: {name}")
    counter.add(delta, labels)


# ── 预定义指标（适配 OmniEvolve 管道） ──────────────────────────────


def record_candidate_generated(generation: int, island_id: str, model: str):
    """候选生成事件."""
    record_counter(
        "omnievolve.candidates.generated",
        delta=1,
        generation=str(generation),
        island=island_id,
        model=model,
    )


def record_evaluation_completed(score: float, passed: bool, duration_ms: float):
    """评估完成事件."""
    record_gauge("omnievolve.evaluation.score", score)
    record_counter("omnievolve.evaluations.completed", delta=1, passed=str(passed).lower())
    record_gauge("omnievolve.evaluation.duration_ms", duration_ms)


def record_slow_loop_triggered(generation: int, alert_level: str):
    """Slow Loop 触发事件."""
    record_counter(
        "omnievolve.slow_loop.triggered",
        delta=1,
        generation=str(generation),
        alert_level=alert_level,
    )


def record_checkpoint_saved(generation: int, candidates: int):
    """检查点保存事件."""
    record_gauge("omnievolve.checkpoint.generation", generation)
    record_gauge("omnievolve.checkpoint.candidates", candidates)
