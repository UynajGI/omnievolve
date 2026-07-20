"""异步进化引擎包装器.

参考 OpenEvolve process_parallel.py + ShinkaEvolve async_runner.py:
    使用 asyncio + ThreadPoolExecutor 并行执行 Fast Loop 候选生成/评估。
    将同步 EvolutionEngine._evolve_one() 并行化，大幅提升 throughput。

架构:
    AsyncEvolutionEngine 不修改 EvolutionEngine 的内部逻辑，
    而是包装 run() 方法：
    - 并行生成/评估候选用 asyncio.to_thread / ThreadPoolExecutor
    - 资源控制用 Semaphore（参考 ShinkaEvolve LogicalSlotPool）
    - 优雅关闭用 asyncio.Event（参考 OpenEvolve signal handler）
"""

from __future__ import annotations

import asyncio
import logging
import signal
from concurrent.futures import ThreadPoolExecutor

from omnievolve.engine.evolution_engine import EvolutionConfig, EvolutionEngine, EvolutionResult

logger = logging.getLogger(__name__)


class AsyncEvolutionEngine:
    """异步进化引擎包装器.

    并行度由 concurrency 参数控制，默认等于 population_size。
    """

    def __init__(
        self,
        engine: EvolutionEngine,
        *,
        concurrency: int | None = None,
        config: EvolutionConfig | None = None,
    ) -> None:
        self._engine = engine
        self._config = config or EvolutionConfig()
        self._concurrency = concurrency or self._config.population_size

        self._shutdown_event = asyncio.Event()
        self._executor: ThreadPoolExecutor | None = None

    async def run(self, initial_code: str, task_name: str) -> EvolutionResult:
        """异步进化主循环.

        使用 ThreadPoolExecutor 并行执行 should_stop_generation() 中的候选生成。
        """
        self._shutdown_event.clear()
        max_workers = max(1, self._concurrency)

        # 注册信号处理
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, self._request_shutdown)
            except NotImplementedError:
                pass  # Windows 不支持 add_signal_handler

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            self._executor = executor

            # 使用同步引擎的初始化流程（初始代码评估等）
            # 然后并行执行后续生成
            result = await self._run_async_loop(initial_code, task_name)

        self._executor = None
        return result

    def _request_shutdown(self) -> None:
        """请求优雅关闭."""
        logger.info("Async shutdown requested")
        self._shutdown_event.set()
        if hasattr(self._engine, "_shutdown_requested"):
            self._engine._shutdown_requested = True  # noqa: SLF001

    async def _run_async_loop(self, initial_code: str, task_name: str) -> EvolutionResult:
        """异步进化循环 — 并行生成候选."""
        # 初始化阶段（同步，复用引擎的 setup）
        engine = self._engine

        engine._ensure_champion_policy()  # noqa: SLF001
        engine._ensure_version_rows()  # noqa: SLF001

        initial_hash = engine._artifact_store.store_text(initial_code, "source")  # noqa: SLF001
        initial_candidate = engine._candidate_repo.create_candidate(  # noqa: SLF001
            experiment_id=engine._experiment_id,  # noqa: SLF001
            task_id=task_name,
            generation=0,
            artifact_hash=initial_hash,
            search_policy_id=engine._champion_policy_id,  # noqa: SLF001
        )
        initial_id = initial_candidate.id

        engine._mcts.add_node(initial_id, parent=None, prior=1.0)  # noqa: SLF001
        engine._evaluate_candidate(initial_id, initial_hash)  # noqa: SLF001
        engine._island_manager.assign_candidate(initial_id, "island_0")  # noqa: SLF001
        engine._experiment_repo.set_baseline(engine._experiment_id, initial_id)  # noqa: SLF001

        sem = asyncio.Semaphore(self._concurrency)

        async def evolve_one(generation: int, slot: int, tid: str) -> None:
            async with sem:
                if self._shutdown_event.is_set():
                    return
                if engine._budget_guard.state.is_exhausted:  # noqa: SLF001
                    return

                island_id = f"island_{slot % engine._config.island_count}"  # noqa: SLF001
                await asyncio.to_thread(
                    engine._evolve_one,  # noqa: SLF001
                    generation,
                    tid,
                    island_id,
                )

        # 主循环
        for gen in range(1, self._config.max_generations + 1):
            if self._shutdown_event.is_set():
                logger.warning("Shutdown at gen %d", gen - 1)
                break
            if engine._budget_guard.state.is_exhausted:  # noqa: SLF001
                logger.warning("Budget exhausted at gen %d", gen)
                break

            engine._current_generation = gen  # noqa: SLF001

            # 并行生成/评估当前代的所有候选
            tasks = [
                asyncio.create_task(evolve_one(gen, s, task_name))
                for s in range(self._config.population_size)
            ]

            done, pending = await asyncio.wait(
                tasks,
                return_when=asyncio.FIRST_EXCEPTION,
            )

            # 检查异常
            for t in done:
                exc = t.exception()
                if exc is not None:
                    logger.error("Candidate evolution failed: %s", exc)

            # 取消未完成的任务（shutdown）
            for t in pending:
                t.cancel()

            # 岛间迁移
            if engine._island_manager.should_migrate(gen):  # noqa: SLF001
                engine._island_manager.migrate(gen)  # noqa: SLF001

            # Slow Loop
            if gen % self._config.health_window_gens == 0:
                engine._run_slow_loop(gen)  # noqa: SLF001

            logger.info(
                "Generation %d done, best=%s",
                gen,
                f"{engine._best_candidate[1]:.4f}"  # noqa: SLF001
                if engine._best_candidate  # noqa: SLF001
                else "N/A",
            )

        return engine._finalize(task_name)  # noqa: SLF001


class SlotPool:
    """参考 ShinkaEvolve LogicalSlotPool: 显式槽池管理.

    用于控制并发候选生成/评估的资源占用。
    """

    def __init__(self, total_slots: int) -> None:
        self._semaphore = asyncio.Semaphore(total_slots)
        self._total = total_slots
        self._active: set[str] = set()

    @property
    def active_count(self) -> int:
        return len(self._active)

    @property
    def available(self) -> int:
        return self._total - len(self._active)

    async def acquire(self, slot_id: str) -> None:
        await self._semaphore.acquire()
        self._active.add(slot_id)

    def release(self, slot_id: str) -> None:
        self._active.discard(slot_id)
        self._semaphore.release()
