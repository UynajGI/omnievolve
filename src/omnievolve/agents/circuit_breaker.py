"""Circuit breaker + rate limiter for LLM API resilience.

P1 hardening: prevents runaway retries and API cost explosions
when upstream LLM services are degraded or unreachable.

CircuitBreaker: standard 3-state breaker (CLOSED → OPEN → HALF_OPEN).
TokenBucketRateLimiter: fixed-window refill token bucket.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    CLOSED = "closed"  # Normal — requests flow through
    OPEN = "open"  # Failing — requests are rejected immediately
    HALF_OPEN = "half_open"  # Testing — one trial request allowed


@dataclass
class CircuitStats:
    state: CircuitState
    failure_count: int
    success_count: int
    open_since: float | None = None
    last_failure: str | None = None


class CircuitBreaker:
    """标准 3 态熔断器.

    CLOSED:  请求正常通过，跟踪失败计数。
    OPEN:    失败超阈值 → 拒绝所有请求，快速失败。
    HALF_OPEN: 超时后 → 允许一次试探；成功则 CLOSED，失败则 OPEN。
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        reset_timeout_sec: float = 60.0,
        half_open_max_trials: int = 1,
    ) -> None:
        self._failure_threshold = failure_threshold
        self._reset_timeout_sec = reset_timeout_sec
        self._half_open_max = half_open_max_trials

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._open_since: float | None = None
        self._half_open_count = 0
        self._last_error: str | None = None
        self._total_failures = 0
        self._total_successes = 0

    # ── state transitions ─────────────────────────────────────

    def on_success(self) -> None:
        """记录一次成功调用."""
        if self._state == CircuitState.HALF_OPEN:
            self._half_open_count += 1
            if self._half_open_count >= self._half_open_max:
                self._transition_to(CircuitState.CLOSED)
        elif self._state == CircuitState.CLOSED:
            # 连续成功 → 逐步降低失败计数（衰减）
            if self._failure_count > 0:
                self._failure_count -= 1
        self._total_successes += 1

    def on_failure(self, error: str = "") -> None:
        """记录一次失败调用."""
        self._failure_count += 1
        self._total_failures += 1
        self._last_error = error

        if self._state == CircuitState.HALF_OPEN:
            self._transition_to(CircuitState.OPEN)
        elif self._state == CircuitState.CLOSED and self._failure_count >= self._failure_threshold:
            self._transition_to(CircuitState.OPEN)

    def can_execute(self) -> bool:
        """检查是否可以执行请求."""
        if self._state == CircuitState.CLOSED:
            return True
        if self._state == CircuitState.OPEN:
            if self._should_attempt_reset():
                self._transition_to(CircuitState.HALF_OPEN)
                return True
            return False
        # HALF_OPEN — allow the trial
        return True

    # ── private ────────────────────────────────────────────────

    def _transition_to(self, new_state: CircuitState) -> None:
        self._state = new_state
        if new_state == CircuitState.OPEN:
            self._open_since = time.time()
            logger.warning(
                "Circuit BREAKER OPEN — %d failures. Last: %s",
                self._failure_count,
                self._last_error,
            )
        elif new_state == CircuitState.CLOSED:
            self._failure_count = 0
            self._open_since = None
            self._half_open_count = 0
            logger.info("Circuit breaker reset — back to CLOSED")
        elif new_state == CircuitState.HALF_OPEN:
            logger.info("Circuit breaker HALF_OPEN — trial request")

    def _should_attempt_reset(self) -> bool:
        if self._open_since is None:
            return True
        elapsed = time.time() - self._open_since
        return elapsed >= self._reset_timeout_sec

    # ── properties ─────────────────────────────────────────────

    @property
    def state(self) -> CircuitState:
        return self._state

    @property
    def is_open(self) -> bool:
        return self._state == CircuitState.OPEN

    @property
    def stats(self) -> CircuitStats:
        return CircuitStats(
            state=self._state,
            failure_count=self._failure_count,
            success_count=self._total_successes,
            open_since=self._open_since,
            last_failure=self._last_error,
        )


class TokenBucketRateLimiter:
    """固定窗口令牌桶速率限制器.

    控制 LLM API 调用频率，防止超配额。
    简化实现：每 refill_interval_sec 补充 capacity 个令牌。
    """

    def __init__(
        self,
        capacity: int = 10,
        refill_interval_sec: float = 1.0,
    ) -> None:
        self._capacity = capacity
        self._refill_interval = refill_interval_sec
        self._tokens = capacity
        self._last_refill = time.time()
        self._total_waited = 0.0

    def acquire(self, tokens: int = 1) -> float:
        """获取令牌（如果不足则等待）.

        Returns:
            等待的秒数
        """
        self._refill()

        if tokens <= self._tokens:
            self._tokens -= tokens
            return 0.0

        # 令牌不足 → 等待到下一次补充
        wait_time = self._refill_interval
        time.sleep(wait_time)
        self._tokens = self._capacity - tokens
        self._total_waited += wait_time
        return wait_time

    def _refill(self) -> None:
        now = time.time()
        elapsed = now - self._last_refill
        intervals = int(elapsed / self._refill_interval)
        if intervals > 0:
            self._tokens = min(self._capacity, self._tokens + intervals * self._capacity)
            self._last_refill = now

    @property
    def available(self) -> int:
        self._refill()
        return self._tokens

    @property
    def stats(self) -> dict:
        return {
            "available": self.available,
            "capacity": self._capacity,
            "total_waited_ms": self._total_waited * 1000,
        }
