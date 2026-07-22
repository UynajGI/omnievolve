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


import math
import time


class AsyncPipelineEngine:
    """原生异步流水线引擎 — prepare/commit 拆分 + EWMA 自适应.

    架构（参考 ShinkaEvolve async_runner.py + Plan A prepare/commit 拆分）：

    Phase A (parallel): _prepare_async() — 并行执行 LLM + sandbox
    Phase B (sequential): _commit_candidate() — 串行合并共享状态
    Phase C (sequential): 岛间迁移 + Slow Loop

    消除竞态条件：Phase A 无共享状态变更，Phase B 串行执行所有状态更新。
    """

    def __init__(
        self,
        engine: EvolutionEngine,
        *,
        max_proposal_slots: int | None = None,
        max_eval_slots: int | None = None,
        ewma_alpha: float = 0.3,
    ) -> None:
        self._engine = engine
        self._config = engine._config  # noqa: SLF001
        self._max_proposal_slots = max_proposal_slots or self._config.population_size
        self._max_eval_slots = max_eval_slots or self._config.population_size
        self._ewma_alpha = ewma_alpha

        self._shutdown_event = asyncio.Event()
        self._sampling_ewma: float | None = None
        self._eval_ewma: float | None = None

        # 复用引擎的 FastLoopStep
        from omnievolve.engine.fast_loop import FastLoopStep
        self._fast_loop = FastLoopStep(engine)

    async def run(self, initial_code: str, task_name: str) -> EvolutionResult:
        """异步流水线主循环."""
        self._shutdown_event.clear()

        # 注册信号处理
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, self._request_shutdown)
            except NotImplementedError:
                pass

        # 同步初始化（复用引擎 setup）
        engine = self._engine
        await asyncio.to_thread(self._sync_init, initial_code, task_name)

        # 主循环
        for gen in range(1, self._config.max_generations + 1):
            if self._shutdown_event.is_set():
                logger.warning("Shutdown at gen %d", gen - 1)
                break
            if engine._budget_guard.state.is_exhausted:  # noqa: SLF001
                logger.warning("Budget exhausted at gen %d", gen)
                break

            engine._current_generation = gen  # noqa: SLF001
            engine._mcts.set_progress(gen, self._config.max_generations)  # noqa: SLF001

            await self._run_generation(gen, task_name)

            logger.info(
                "Generation %d done, best=%s",
                gen,
                f"{engine._best_candidate[1]:.4f}"  # noqa: SLF001
                if engine._best_candidate  # noqa: SLF001
                else "N/A",
            )

        return await asyncio.to_thread(engine._finalize, task_name)  # noqa: SLF001

    def _request_shutdown(self) -> None:
        logger.info("Pipeline shutdown requested")
        self._shutdown_event.set()
        if hasattr(self._engine, "_shutdown_requested"):
            self._engine._shutdown_requested = True  # noqa: SLF001

    def _sync_init(self, initial_code: str, task_name: str) -> None:
        """同步初始化 — 复用引擎的 setup 流程."""
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
        engine._mcts.add_node(initial_candidate.id, parent=None, prior=1.0)  # noqa: SLF001
        engine._evaluate_candidate(initial_candidate.id, initial_hash)  # noqa: SLF001
        engine._island_manager.assign_candidate(initial_candidate.id, "island_0")  # noqa: SLF001
        engine._experiment_repo.set_baseline(engine._experiment_id, initial_candidate.id)  # noqa: SLF001

    async def _run_generation(self, gen: int, task_name: str) -> None:
        """执行一代的完整流水线."""
        engine = self._engine

        # Phase A: 并行准备（LLM + sandbox，无共享状态变更）
        target = self._compute_pipeline_target()
        tasks = []
        for i in range(target):
            if self._shutdown_event.is_set() or engine._budget_guard.state.is_exhausted:  # noqa: SLF001
                break
            island_id = f"island_{i % engine._config.island_count}"  # noqa: SLF001
            tasks.append(asyncio.create_task(
                self._prepare_async(gen, task_name, island_id)
            ))

        prepared_results = await asyncio.gather(*tasks, return_exceptions=True)

        # Phase B: 顺序提交（串行合并共享状态）
        for result in prepared_results:
            if isinstance(result, Exception):
                logger.error("Prepare failed: %s", result, exc_info=result)
                continue
            if result is not None:
                try:
                    self._commit_candidate(result)
                except Exception:
                    logger.error("Commit failed for %s", result.candidate_id, exc_info=True)

        # Phase C: 后代同步
        if engine._island_manager.should_migrate(gen):  # noqa: SLF001
            await asyncio.to_thread(engine._island_manager.migrate, gen)  # noqa: SLF001

        if gen % self._config.health_window_gens == 0:  # noqa: SLF001
            await asyncio.to_thread(engine._run_slow_loop, gen)  # noqa: SLF001

        # 每代后消费向量索引 Outbox
        if engine._vector_indexer:  # noqa: SLF001
            await asyncio.to_thread(self._safe_process_batch)

    def _safe_process_batch(self) -> None:
        try:
            self._engine._vector_indexer.process_batch()  # noqa: SLF001
        except Exception:
            logger.debug("Vector batch processing failed", exc_info=True)

    async def _prepare_async(self, gen: int, task_name: str, island_id: str):
        """Phase A: 并行执行 prepare — 无共享状态变更."""
        start = time.perf_counter()
        result = await asyncio.to_thread(
            self._fast_loop.prepare, gen, task_name, island_id
        )
        elapsed = time.perf_counter() - start
        self._update_ewma("sampling", elapsed)
        return result

    def _commit_candidate(self, prepared) -> None:
        """Phase B: 串行合并共享状态."""
        start = time.perf_counter()
        self._fast_loop.commit_result(prepared)
        elapsed = time.perf_counter() - start
        self._update_ewma("commit", elapsed)

    def _update_ewma(self, kind: str, elapsed: float) -> None:
        """更新 EWMA 计时."""
        if kind == "sampling":
            if self._sampling_ewma is None:
                self._sampling_ewma = elapsed
            else:
                self._sampling_ewma = (
                    self._ewma_alpha * elapsed + (1 - self._ewma_alpha) * self._sampling_ewma
                )
        elif kind == "commit":
            if self._eval_ewma is None:
                self._eval_ewma = elapsed
            else:
                self._eval_ewma = (
                    self._ewma_alpha * elapsed + (1 - self._ewma_alpha) * self._eval_ewma
                )

    def _compute_pipeline_target(self) -> int:
        """EWMA 自适应提案目标."""
        base = self._config.population_size
        if self._sampling_ewma is None or self._eval_ewma is None:
            return base  # 冷启动
        ratio = min(self._sampling_ewma / max(self._eval_ewma, 0.01), 3.0)
        return min(math.ceil(base * ratio), self._max_proposal_slots)
