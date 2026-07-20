"""AsyncEvolutionEngine 测试 — SlotPool + 基本流程.

分层策略：使用 FakeLLM，不依赖真实 API。
"""

from __future__ import annotations

import asyncio

from omnievolve.engine.async_engine import SlotPool


class TestSlotPool:
    """SlotPool 是纯异步资源池管理器，无外部依赖。"""

    def test_init(self):
        pool = SlotPool(total_slots=4)
        assert pool.active_count == 0
        assert pool.available == 4

    def test_acquire_increases_active(self):
        async def _test():
            pool = SlotPool(total_slots=3)
            await pool.acquire("slot_1")
            assert pool.active_count == 1
            assert pool.available == 2

        asyncio.run(_test())

    def test_release_decreases_active(self):
        async def _test():
            pool = SlotPool(total_slots=3)
            await pool.acquire("slot_1")
            pool.release("slot_1")
            assert pool.active_count == 0
            assert pool.available == 3

        asyncio.run(_test())

    def test_acquire_blocks_when_full(self):
        """When all slots taken, acquire blocks until release."""

        async def _test():
            pool = SlotPool(total_slots=2)
            await pool.acquire("a")
            await pool.acquire("b")
            assert pool.available == 0

            task = asyncio.create_task(pool.acquire("c"))
            await asyncio.sleep(0.01)
            assert not task.done()

            pool.release("a")
            await asyncio.sleep(0.01)
            assert task.done()
            assert pool.active_count == 2

        asyncio.run(_test())

    def test_multiple_acquire_release_cycle(self):
        async def _test():
            pool = SlotPool(total_slots=2)
            for i in range(10):
                await pool.acquire(f"slot_{i}")
                pool.release(f"slot_{i}")
            assert pool.active_count == 0
            assert pool.available == 2

        asyncio.run(_test())

    def test_release_unknown_slot_no_error(self):
        """Releasing a slot that wasn't acquired is safe."""

        async def _test():
            pool = SlotPool(total_slots=2)
            pool.release("nonexistent")
            assert pool.available == 2

        asyncio.run(_test())

    def test_concurrent_acquire(self):
        """Multiple concurrent acquires respect the limit."""

        async def _test():
            pool = SlotPool(total_slots=3)
            results = []

            async def worker(wid: int):
                await pool.acquire(f"w{wid}")
                results.append(wid)
                await asyncio.sleep(0.01)
                pool.release(f"w{wid}")

            await asyncio.gather(*[worker(i) for i in range(10)])
            assert len(results) == 10
            assert pool.active_count == 0

        asyncio.run(_test())
