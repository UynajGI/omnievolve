"""模块化性能评估组件.

双层架构:
- 架构级: PipelineProfiler + @profile_step + StepTimer (本文件)
- 行级: scalene (外部工具, scripts/profile_pipeline.py)

用法:
    # 装饰器
    @profile_step("mcts.select")
    def select(self, root_id): ...

    # 上下文管理器
    with StepTimer("vector_index.batch"):
        indexer.process_batch(100)

    # 全管线 profiling
    profiler = PipelineProfiler(engine, track_memory=True)
    result = profiler.run(initial_code, task_name, generations=3)
    profiler.report()
"""

from __future__ import annotations

import functools
import json
import statistics
import time
import tracemalloc
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = __import__("logging").getLogger(__name__)

# 全局 profiler 引用（供 @profile_step 使用）
_active_profiler: PipelineProfiler | None = None


@dataclass
class StepRecord:
    """单个步骤的性能记录."""

    name: str
    wall_time_ms: float
    cpu_time_ms: float
    mem_peak_mb: float = 0.0
    rss_delta_mb: float = 0.0
    generation: int = 0
    metadata: dict = field(default_factory=dict)


class StepTimer:
    """上下文管理器 — 手动标记代码块的性能采集.

    Usage:
        with StepTimer("my_step", profiler=engine._profiler) as t:
            do_work()
        # t.record 包含采集数据
    """

    def __init__(
        self,
        name: str,
        *,
        profiler: PipelineProfiler | None = None,
        generation: int = 0,
        track_memory: bool = True,
        metadata: dict | None = None,
    ) -> None:
        self.name = name
        self._profiler = profiler or _active_profiler
        self._generation = generation
        self._track_memory = track_memory
        self._metadata = metadata or {}
        self._wall_start = 0.0
        self._cpu_start = 0.0
        self._rss_start = 0.0
        self.record: StepRecord | None = None

    def __enter__(self) -> StepTimer:
        self._wall_start = time.perf_counter()
        self._cpu_start = time.process_time()
        if self._track_memory:
            self._rss_start = _get_rss_mb()
        return self

    def __exit__(self, *exc: Any) -> None:
        wall_ms = (time.perf_counter() - self._wall_start) * 1000
        cpu_ms = (time.process_time() - self._cpu_start) * 1000
        rss_delta = _get_rss_mb() - self._rss_start if self._track_memory else 0.0

        self.record = StepRecord(
            name=self.name,
            wall_time_ms=wall_ms,
            cpu_time_ms=cpu_ms,
            rss_delta_mb=rss_delta,
            generation=self._generation,
            metadata=self._metadata,
        )

        if self._profiler:
            self._profiler._records.append(self.record)


def profile_step(name: str) -> Any:
    """装饰器 — 标记任意函数为 profile 步骤.

    仅当全局 _active_profiler 存在时采集，否则零开销。
    """

    def decorator(func: Any) -> Any:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            if _active_profiler is None:
                return func(*args, **kwargs)
            with StepTimer(name, profiler=_active_profiler):
                return func(*args, **kwargs)

        return wrapper

    return decorator


class PipelineProfiler:
    """架构级全管线性能分析器.

    嵌入 EvolutionEngine 运行，按步骤采集 wall-time / CPU / 内存。
    profiler=None 时零开销（条件式采集）。
    """

    def __init__(
        self,
        engine: Any,
        *,
        track_memory: bool = True,
        steps: list[str] | None = None,
    ) -> None:
        self._engine = engine
        self._track_memory = track_memory
        self._steps_filter = set(steps) if steps else None
        self._records: list[StepRecord] = []
        self._result: Any = None

    def run(self, initial_code: str, task_name: str, generations: int | None = None) -> Any:
        """运行带 profiling 的进化循环.

        Args:
            initial_code: 初始代码
            task_name: 任务名
            generations: 覆盖配置中的代数（可选）
        """
        global _active_profiler

        if generations is not None:
            self._engine._config.max_generations = generations  # noqa: SLF001

        # 挂载到 engine
        self._engine._profiler = self  # noqa: SLF001
        _active_profiler = self

        if self._track_memory:
            tracemalloc.start()

        try:
            self._result = self._engine.run(initial_code, task_name)
        finally:
            _active_profiler = None
            self._engine._profiler = None  # noqa: SLF001
            if self._track_memory and tracemalloc.is_tracing():
                tracemalloc.stop()

        return self._result

    def record_step(
        self,
        name: str,
        wall_ms: float,
        cpu_ms: float = 0.0,
        generation: int = 0,
        metadata: dict | None = None,
    ) -> None:
        """手动记录一个步骤（供 fast_loop 内部调用）."""
        if self._steps_filter and name not in self._steps_filter:
            return
        self._records.append(
            StepRecord(
                name=name,
                wall_time_ms=wall_ms,
                cpu_time_ms=cpu_ms or wall_ms,
                generation=generation,
                metadata=metadata or {},
            )
        )

    @contextmanager
    def step(self, name: str, generation: int = 0) -> Generator[None, None, None]:
        """上下文管理器 — 在 pipeline 代码中使用."""
        if self._steps_filter and name not in self._steps_filter:
            yield
            return

        wall_start = time.perf_counter()
        cpu_start = time.process_time()
        yield
        wall_ms = (time.perf_counter() - wall_start) * 1000
        cpu_ms = (time.process_time() - cpu_start) * 1000

        self._records.append(
            StepRecord(
                name=name,
                wall_time_ms=wall_ms,
                cpu_time_ms=cpu_ms,
                rss_delta_mb=0.0,
                generation=generation,
            )
        )

    def percentiles(self, step_name: str) -> dict[str, float]:
        """计算指定步骤的 P50/P95/P99 延迟."""
        times = sorted(r.wall_time_ms for r in self._records if r.name == step_name)
        if not times:
            return {"p50": 0, "p95": 0, "p99": 0, "count": 0}
        n = len(times)
        return {
            "p50": times[int(n * 0.5)] if n > 1 else times[0],
            "p95": times[min(int(n * 0.95), n - 1)],
            "p99": times[min(int(n * 0.99), n - 1)],
            "mean": statistics.mean(times),
            "count": n,
        }

    def hotspots(self, top_k: int = 5) -> list[tuple[str, float]]:
        """返回总耗时最高的 top-k 步骤."""
        totals: dict[str, float] = {}
        for r in self._records:
            totals[r.name] = totals.get(r.name, 0) + r.wall_time_ms
        sorted_steps = sorted(totals.items(), key=lambda x: x[1], reverse=True)
        return sorted_steps[:top_k]

    def report(self) -> None:
        """输出 rich 终端表格."""
        try:
            from rich.console import Console
            from rich.table import Table
        except ImportError:
            self._report_plain()
            return

        console = Console()
        table = Table(title="Pipeline Profiling Report")
        table.add_column("Step", style="cyan")
        table.add_column("Count", justify="right")
        table.add_column("P50 (ms)", justify="right")
        table.add_column("P95 (ms)", justify="right")
        table.add_column("P99 (ms)", justify="right")
        table.add_column("Total (ms)", justify="right")
        table.add_column("% Total", justify="right")

        # 按步骤聚合
        step_names = sorted(set(r.name for r in self._records))
        grand_total = sum(r.wall_time_ms for r in self._records)

        for name in step_names:
            p = self.percentiles(name)
            total = sum(r.wall_time_ms for r in self._records if r.name == name)
            pct = (total / grand_total * 100) if grand_total > 0 else 0
            table.add_row(
                name,
                str(p["count"]),
                f"{p['p50']:.1f}",
                f"{p['p95']:.1f}",
                f"{p['p99']:.1f}",
                f"{total:.1f}",
                f"{pct:.1f}%",
            )

        console.print(table)

        # Hotspots
        console.print("\n[bold]Top Hotspots:[/bold]")
        for name, total in self.hotspots(5):
            console.print(f"  {name}: {total:.1f} ms")

    def _report_plain(self) -> None:
        """纯文本输出（无 rich 时）."""
        print(f"{'Step':<20} {'Count':>6} {'P50':>8} {'P95':>8} {'Total':>10}")
        print("-" * 60)
        for name in sorted(set(r.name for r in self._records)):
            p = self.percentiles(name)
            total = sum(r.wall_time_ms for r in self._records if r.name == name)
            print(f"{name:<20} {p['count']:>6} {p['p50']:>8.1f} {p['p95']:>8.1f} {total:>10.1f}")

    def export_json(self, path: str | Path) -> None:
        """导出 JSON 报告."""
        data = {
            "hotspots": self.hotspots(10),
            "steps": {},
            "records_count": len(self._records),
        }
        for name in set(r.name for r in self._records):
            data["steps"][name] = self.percentiles(name)

        Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False))
        logger.info("Profiling report exported to %s", path)


def _get_rss_mb() -> float:
    """获取当前进程 RSS 内存 (MB)."""
    try:
        import psutil

        return psutil.Process().memory_info().rss / (1024 * 1024)
    except ImportError:
        return 0.0
