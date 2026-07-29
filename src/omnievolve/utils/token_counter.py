"""Token / API / compute 计量.

S5-12: token/费用预算硬门
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

# 常见模型定价 (USD per 1K tokens) - 示例值，需按实际更新
MODEL_PRICING: dict[str, dict[str, float]] = {
    "gpt-4o": {"input": 0.0025, "output": 0.01},
    "gpt-4o-mini": {"input": 0.00015, "output": 0.0006},
    "gpt-4-turbo": {"input": 0.01, "output": 0.03},
    "claude-3-5-sonnet": {"input": 0.003, "output": 0.015},
    "claude-3-opus": {"input": 0.015, "output": 0.075},
}


@dataclass
class UsageRecord:
    """单次使用记录."""

    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float | None = None
    cost_known: bool = False
    compute_sec: float = 0.0


@dataclass
class BudgetState:
    """预算状态."""

    token_budget: int = 2_000_000
    cost_budget_usd: float = 100.0
    compute_budget_sec: float | None = None

    used_tokens: int = 0
    used_cost_usd: float = 0.0
    cost_known: bool = True
    used_compute_sec: float = 0.0

    def __post_init__(self) -> None:
        """Normalize the public ``0 = unlimited`` compute-budget convention."""
        if self.compute_budget_sec == 0:
            self.compute_budget_sec = None
        elif self.compute_budget_sec is not None and self.compute_budget_sec < 0:
            raise ValueError("compute_budget_sec must be non-negative or None")

    @property
    def remaining_tokens(self) -> int:
        return max(0, self.token_budget - self.used_tokens)

    @property
    def remaining_cost(self) -> float | None:
        if not self.cost_known:
            return None
        return max(0.0, self.cost_budget_usd - self.used_cost_usd)

    @property
    def remaining_compute(self) -> float | None:
        if self.compute_budget_sec is None:
            return None
        return max(0.0, self.compute_budget_sec - self.used_compute_sec)

    @property
    def token_ratio(self) -> float:
        if self.token_budget <= 0:
            return 1.0
        return self.used_tokens / self.token_budget

    @property
    def is_exhausted(self) -> bool:
        if self.remaining_tokens <= 0:
            return True
        if self.remaining_cost is not None and self.remaining_cost <= 0:
            return True
        if self.remaining_compute is not None and self.remaining_compute <= 0:
            return True
        return False


class TokenCounter:
    """Token / 费用计量器."""

    def __init__(
        self,
        db: Any | None = None,
        experiment_id: str | None = None,
    ) -> None:
        self._db = db
        self._experiment_id = experiment_id
        self._total_input = 0
        self._total_output = 0
        self._total_cost = 0.0
        self._cost_known = True
        self._total_compute = 0.0

    def estimate_cost(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
    ) -> float | None:
        """Return catalog cost, or ``None`` when the model price is unknown."""
        pricing = MODEL_PRICING.get(model)
        if pricing is None:
            return None
        return input_tokens * pricing["input"] / 1000 + output_tokens * pricing["output"] / 1000

    def record(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        compute_sec: float = 0.0,
        *,
        cost_usd: float | None = None,
        cost_known: bool | None = None,
    ) -> UsageRecord:
        """记录使用量."""
        if cost_known is None:
            cost_usd = self.estimate_cost(model, input_tokens, output_tokens)
            cost_known = cost_usd is not None
        elif cost_known and cost_usd is None:
            raise ValueError("cost_usd is required when cost_known=True")
        record = UsageRecord(
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd,
            cost_known=cost_known,
            compute_sec=compute_sec,
        )

        self._total_input += input_tokens
        self._total_output += output_tokens
        if cost_usd is not None:
            self._total_cost += cost_usd
        if not cost_known:
            self._cost_known = False
        self._total_compute += compute_sec

        return record

    @property
    def total_tokens(self) -> int:
        return self._total_input + self._total_output

    @property
    def total_cost(self) -> float | None:
        return self._total_cost if self._cost_known else None

    @property
    def known_cost(self) -> float:
        """Known subtotal, never a substitute for total cost when incomplete."""
        return self._total_cost

    @property
    def cost_known(self) -> bool:
        return self._cost_known

    @property
    def total_compute_sec(self) -> float:
        return self._total_compute

    def get_stats(self) -> dict[str, Any]:
        """获取统计."""
        return {
            "total_input_tokens": self._total_input,
            "total_output_tokens": self._total_output,
            "total_tokens": self.total_tokens,
            "total_cost_usd": self.total_cost,
            "known_cost_usd": self._total_cost,
            "cost_known": self._cost_known,
            "total_compute_sec": self._total_compute,
        }

    def restore_stats(self, state: dict[str, Any] | None) -> None:
        """Restore aggregate counters from a completed-generation checkpoint."""
        if not state:
            return
        self._total_input = int(state.get("total_input_tokens", 0))
        self._total_output = int(state.get("total_output_tokens", 0))
        raw_cost = state.get("known_cost_usd", state.get("total_cost_usd", 0.0))
        self._total_cost = float(raw_cost or 0.0)
        self._cost_known = bool(state.get("cost_known", raw_cost is not None))
        self._total_compute = float(state.get("total_compute_sec", 0.0))


class BudgetGuard:
    """预算硬门 - 阻止超预算的操作."""

    def __init__(self, state: BudgetState) -> None:
        self._state = state
        self._counter = TokenCounter()

    @property
    def state(self) -> BudgetState:
        return self._state

    @property
    def counter(self) -> TokenCounter:
        return self._counter

    def can_proceed(self, estimated_tokens: int = 0) -> bool:
        """检查是否可以继续."""
        if self._state.is_exhausted:
            return False
        if self._state.remaining_tokens < estimated_tokens:
            return False
        return True

    def consume(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        compute_sec: float = 0.0,
        *,
        cost_usd: float | None = None,
        cost_known: bool | None = None,
    ) -> UsageRecord:
        """消耗预算."""
        record = self._counter.record(
            model,
            input_tokens,
            output_tokens,
            compute_sec,
            cost_usd=cost_usd,
            cost_known=cost_known,
        )

        self._state.used_tokens += record.input_tokens + record.output_tokens
        if record.cost_usd is not None:
            self._state.used_cost_usd += record.cost_usd
        if not record.cost_known:
            self._state.cost_known = False
        self._state.used_compute_sec += record.compute_sec

        if self._state.is_exhausted:
            logger.warning(
                f"Budget exhausted: tokens={self._state.used_tokens}/{self._state.token_budget}, "
                f"cost=${self._state.used_cost_usd:.2f}/${self._state.cost_budget_usd:.2f}, "
                f"cost_known={self._state.cost_known}"
            )

        return record

    def check_budget(self) -> dict[str, Any]:
        """检查预算状态."""
        return {
            "token_budget": self._state.token_budget,
            "token_used": self._state.used_tokens,
            "token_remaining": self._state.remaining_tokens,
            "token_ratio": self._state.token_ratio,
            "cost_budget": self._state.cost_budget_usd,
            "cost_used": (
                self._state.used_cost_usd if self._state.cost_known else None
            ),
            "known_cost_used": self._state.used_cost_usd,
            "cost_known": self._state.cost_known,
            "cost_remaining": self._state.remaining_cost,
            "is_exhausted": self._state.is_exhausted,
        }

    def snapshot_state(self) -> dict[str, Any]:
        """Serialize hard-budget and aggregate usage state."""
        return {
            "token_budget": self._state.token_budget,
            "cost_budget_usd": self._state.cost_budget_usd,
            "compute_budget_sec": self._state.compute_budget_sec,
            "used_tokens": self._state.used_tokens,
            "used_cost_usd": self._state.used_cost_usd,
            "cost_known": self._state.cost_known,
            "used_compute_sec": self._state.used_compute_sec,
            "counter": self._counter.get_stats(),
        }

    def restore_state(self, state: dict[str, Any] | None) -> None:
        """Restore usage while rejecting incompatible budget ceilings."""
        if not state:
            return
        expected = (
            self._state.token_budget,
            self._state.cost_budget_usd,
            self._state.compute_budget_sec,
        )
        actual = (
            int(state.get("token_budget", expected[0])),
            float(state.get("cost_budget_usd", expected[1])),
            state.get("compute_budget_sec", expected[2]),
        )
        if actual != expected:
            raise ValueError("checkpoint budget ceilings do not match runtime configuration")
        self._state.used_tokens = max(
            self._state.used_tokens,
            int(state.get("used_tokens", 0)),
        )
        self._state.used_cost_usd = max(
            self._state.used_cost_usd,
            float(state.get("used_cost_usd", 0.0)),
        )
        self._state.cost_known = self._state.cost_known and bool(
            state.get("cost_known", True)
        )
        self._state.used_compute_sec = max(
            self._state.used_compute_sec,
            float(state.get("used_compute_sec", 0.0)),
        )
        self._counter.restore_stats(state.get("counter"))


def estimate_tokens(text: str) -> int:
    """粗略估算 token 数（约 4 字符 = 1 token）."""
    return max(1, len(text) // 4)
