"""异步进化引擎测试.

验证 AsyncEvolutionEngine 的并行能力和状态一致性。
"""

from __future__ import annotations

import asyncio

import pytest

from omnievolve.engine.async_engine import SlotPool

pytestmark = pytest.mark.unit


def _run_async(coro):
    """在同步测试中执行协程."""
    return asyncio.run(coro)


class TestSlotPool:
    """SlotPool 槽池测试."""

    def test_slot_pool_basic(self) -> None:
        pool = SlotPool(total_slots=3)
        assert pool.available == 3
        assert pool.active_count == 0

    def test_acquire_release(self) -> None:
        async def _test() -> None:
            pool = SlotPool(total_slots=2)
            await pool.acquire("slot-1")
            assert pool.active_count == 1
            assert pool.available == 1

            await pool.acquire("slot-2")
            assert pool.active_count == 2
            assert pool.available == 0

            pool.release("slot-1")
            assert pool.active_count == 1
            assert pool.available == 1

        _run_async(_test())

    def test_concurrency_limit(self) -> None:
        async def _test() -> None:
            pool = SlotPool(total_slots=2)
            await pool.acquire("a")
            await pool.acquire("b")

            acquired: list[str] = []

            async def try_acquire(sid: str) -> None:
                await pool.acquire(sid)
                acquired.append(sid)
                pool.release(sid)

            # 第三个槽需等待
            _task = asyncio.create_task(try_acquire("c"))
            await asyncio.sleep(0.01)
            assert "c" not in acquired  # 应被阻塞

            pool.release("a")
            await asyncio.sleep(0.01)
            assert "c" in acquired  # 释放后应获得

        _run_async(_test())
