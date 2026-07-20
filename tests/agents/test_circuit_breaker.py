"""CircuitBreaker + TokenBucketRateLimiter 测试.

P1 韧性 — 熔断器防止失控重试，速率限制器防止配额溢出。
"""

from __future__ import annotations

import time

from omnievolve.agents.circuit_breaker import (
    CircuitBreaker,
    CircuitState,
    TokenBucketRateLimiter,
)


class TestCircuitBreaker:
    def test_initial_state_closed(self):
        cb = CircuitBreaker()
        assert cb.state == CircuitState.CLOSED
        assert not cb.is_open
        assert cb.can_execute()

    def test_failures_below_threshold_keep_closed(self):
        cb = CircuitBreaker(failure_threshold=5)
        for _ in range(4):
            cb.on_failure("timeout")
        assert cb.state == CircuitState.CLOSED
        assert cb.can_execute()

    def test_failures_reach_threshold_opens(self):
        cb = CircuitBreaker(failure_threshold=3)
        for _ in range(3):
            cb.on_failure("server error")
        assert cb.state == CircuitState.OPEN
        assert cb.is_open
        assert not cb.can_execute()

    def test_open_rejects_all_calls(self):
        cb = CircuitBreaker(failure_threshold=2, reset_timeout_sec=30)
        cb.on_failure("err")
        cb.on_failure("err")
        assert cb.state == CircuitState.OPEN
        for _ in range(10):
            assert not cb.can_execute()

    def test_reset_after_timeout(self):
        """After reset_timeout, circuit transitions to HALF_OPEN."""
        cb = CircuitBreaker(failure_threshold=2, reset_timeout_sec=0.01)
        cb.on_failure("err")
        cb.on_failure("err")
        assert cb.state == CircuitState.OPEN

        # Wait for timeout
        time.sleep(0.02)
        assert cb.can_execute()  # transitions to HALF_OPEN
        assert cb.state == CircuitState.HALF_OPEN

    def test_half_open_success_closes(self):
        cb = CircuitBreaker(failure_threshold=2, reset_timeout_sec=0.01)
        cb.on_failure("err")
        cb.on_failure("err")
        time.sleep(0.02)
        assert cb.can_execute()
        assert cb.state == CircuitState.HALF_OPEN

        cb.on_success()
        assert cb.state == CircuitState.CLOSED
        assert cb.can_execute()

    def test_half_open_failure_reopens(self):
        cb = CircuitBreaker(failure_threshold=2, reset_timeout_sec=0.01)
        cb.on_failure("err")
        cb.on_failure("err")
        time.sleep(0.02)
        cb.can_execute()
        assert cb.state == CircuitState.HALF_OPEN

        cb.on_failure("still failing")
        assert cb.state == CircuitState.OPEN

    def test_success_in_closed_dampens_failures(self):
        """Each success in CLOSED state reduces failure count by 1."""
        cb = CircuitBreaker(failure_threshold=5)
        for _ in range(3):
            cb.on_failure("err")
        cb.on_success()
        cb.on_success()
        cb.on_success()
        # 3 failures - 3 successes = 0 failures
        # But 2 more failures needed to hit threshold
        for _ in range(5):
            cb.on_failure("err")
        assert cb.state == CircuitState.OPEN

    def test_stats_report(self):
        cb = CircuitBreaker(failure_threshold=3)
        cb.on_failure("timeout")
        cb.on_success()
        stats = cb.stats
        assert stats.state == CircuitState.CLOSED
        assert stats.failure_count == 0  # dampened by success
        assert stats.success_count == 1

    def test_quick_reset_cycle(self):
        """Full cycle: CLOSED → OPEN → HALF_OPEN → CLOSED."""
        cb = CircuitBreaker(failure_threshold=2, reset_timeout_sec=0.01)
        cb.on_failure("e1")
        cb.on_failure("e2")
        assert cb.state == CircuitState.OPEN

        time.sleep(0.02)
        assert cb.can_execute()
        assert cb.state == CircuitState.HALF_OPEN

        cb.on_success()
        assert cb.state == CircuitState.CLOSED


class TestTokenBucketRateLimiter:
    def test_initial_tokens_full(self):
        rl = TokenBucketRateLimiter(capacity=10)
        assert rl.available == 10

    def test_acquire_consumes_token(self):
        rl = TokenBucketRateLimiter(capacity=5)
        waited = rl.acquire(tokens=1)
        assert waited == 0.0
        assert rl.available == 4  # 5 - 1

    def test_acquire_multiple_tokens(self):
        rl = TokenBucketRateLimiter(capacity=10)
        waited = rl.acquire(tokens=7)
        assert waited == 0.0
        assert rl.available == 3

    def test_refill_happens_automatically(self):
        """After refill_interval, tokens replenish."""
        rl = TokenBucketRateLimiter(capacity=5, refill_interval_sec=0.05)
        rl.acquire(tokens=5)  # exhaust
        assert rl.available == 0

        time.sleep(0.06)
        assert rl.available == 5  # refilled

    def test_acquire_waits_when_exhausted(self):
        """When tokens exhausted, acquire blocks until refill."""
        rl = TokenBucketRateLimiter(capacity=3, refill_interval_sec=0.03)
        rl.acquire(tokens=3)  # exhaust
        assert rl.available == 0

        # This will sleep ~0.03s waiting for refill
        start = time.time()
        waited = rl.acquire(tokens=1)
        elapsed = time.time() - start
        assert waited > 0
        assert elapsed >= 0.02  # waited at least ~20ms

    def test_many_acquires_dont_overflow(self):
        rl = TokenBucketRateLimiter(capacity=100, refill_interval_sec=0.01)
        for _ in range(50):
            rl.acquire(tokens=1)
        assert rl.available >= 0
