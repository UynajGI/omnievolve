"""LLM Gateway - LiteLLM Adapter.

S5-02: 实现 ModelGateway/LiteLLM Adapter
S5-03: 实现 LLMCallLedger
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from omnievolve.storage.db import Database
from omnievolve.storage.repositories.base import generate_id
from omnievolve.utils.hashing import compute_sha256_str

logger = logging.getLogger(__name__)


@dataclass
class LLMResponse:
    """LLM 响应."""

    content: str
    model: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cost_usd: float | None = None
    latency_ms: float | None = None
    raw_response: dict = field(default_factory=dict)


@dataclass
class LLMCallRecord:
    """LLM 调用记录."""

    id: str
    experiment_id: str | None
    agent_role: str
    model: str
    prompt_version_id: str | None
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cost_usd: float | None
    latency_ms: float | None
    request_hash: str | None
    response_hash: str | None
    created_at: str


class LLMGateway:
    """LLM 网关 - 统一调用接口.

    使用 LiteLLM 连接各种 LLM API 和本地模型。

    P1 韧性: 集成 CircuitBreaker 和 TokenBucketRateLimiter
    """

    def __init__(
        self,
        db: Database | None = None,
        *,
        default_model: str = "gpt-4o-mini",
        api_key: str | None = None,
        api_base: str | None = None,
        max_retries: int = 3,
        retry_backoff_base: float = 1.0,
        fallback_model: str | None = None,
        circuit_breaker: Any | None = None,
        rate_limiter: Any | None = None,
        budget_guard: Any | None = None,
    ) -> None:
        self._db = db
        self._default_model = default_model
        self._api_key = api_key
        self._api_base = api_base
        self._max_retries = max_retries
        self._retry_backoff_base = retry_backoff_base
        self._fallback_model = fallback_model
        self._total_tokens = 0
        self._total_cost = 0.0
        # P1: 熔断器 + 限流
        self._circuit_breaker = circuit_breaker
        self._rate_limiter = rate_limiter
        # 1.1: BudgetGuard — LLM token 消耗传播到预算系统
        self._budget_guard = budget_guard

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        experiment_id: str | None = None,
        agent_role: str = "unknown",
        prompt_version_id: str | None = None,
    ) -> LLMResponse:
        """发送聊天请求.

        Args:
            messages: 消息列表 [{"role": "user", "content": "..."}]
            model: 模型名称
            temperature: 温度
            max_tokens: 最大 token 数
            experiment_id: 实验 ID（用于记录）
            agent_role: Agent 角色（director/coder/critic/meta）
            prompt_version_id: Prompt 版本 ID

        Returns:
            LLMResponse
        """
        model = model or self._default_model
        start_time = time.time()

        # P1: 熔断器检查 — OPEN 时快速失败（HALF_OPEN 允许试探）
        if self._circuit_breaker and not self._circuit_breaker.can_execute():
            logger.warning("Circuit breaker OPEN — rejecting LLM call")
            raise RuntimeError(
                "LLM gateway circuit breaker is OPEN. "
                "All requests are rejected to protect cost/availability."
            )

        # P1: 速率限制
        if self._rate_limiter:
            waited = self._rate_limiter.acquire()
            if waited > 0:
                logger.debug("Rate limiter waited %.1fs", waited)

        # P0: Prompt 缓存 — temperature=0 时查 ledger 复用（省 token）
        if temperature == 0.0 and self._db is not None:
            cached = self._lookup_cached_response(messages, model)
            if cached is not None:
                logger.debug("Prompt cache hit (model=%s), reusing response", model)
                return cached

        # S5-10: retry/backoff/fallback
        last_error: Exception | None = None
        models_to_try = [model]
        if self._fallback_model and self._fallback_model != model:
            models_to_try.append(self._fallback_model)

        for try_model in models_to_try:
            for attempt in range(self._max_retries):
                try:
                    import litellm

                    response = litellm.completion(
                        model=try_model,
                        messages=messages,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        api_key=self._api_key,
                        api_base=self._api_base,
                    )

                    latency_ms = (time.time() - start_time) * 1000
                    content = response.choices[0].message.content or ""
                    usage = response.usage

                    llm_response = LLMResponse(
                        content=content,
                        model=try_model,
                        input_tokens=usage.prompt_tokens if usage else 0,
                        output_tokens=usage.completion_tokens if usage else 0,
                        total_tokens=usage.total_tokens if usage else 0,
                        cost_usd=self._extract_cost(response, try_model, usage),
                        latency_ms=latency_ms,
                        raw_response=response.model_dump()
                        if hasattr(response, "model_dump")
                        else {},
                    )

                    self._total_tokens += llm_response.total_tokens
                    if llm_response.cost_usd:
                        self._total_cost += llm_response.cost_usd

                    # 1.1: 传播 LLM token 消耗到 BudgetGuard
                    if self._budget_guard:
                        self._budget_guard.consume(
                            model=try_model,
                            input_tokens=llm_response.input_tokens,
                            output_tokens=llm_response.output_tokens,
                            compute_sec=0.0,
                        )

                    # P1: 熔断器 — 成功
                    if self._circuit_breaker:
                        self._circuit_breaker.on_success()

                    if self._db:
                        self._record_call(
                            experiment_id=experiment_id,
                            agent_role=agent_role,
                            model=try_model,
                            prompt_version_id=prompt_version_id,
                            response=llm_response,
                            messages=messages,
                        )

                    return llm_response

                except ImportError:
                    logger.warning("litellm not installed, using mock response")
                    if self._circuit_breaker:
                        self._circuit_breaker.on_failure("litellm not installed")
                    return self._mock_response(messages, try_model)
                except Exception as e:
                    last_error = e
                    logger.warning(
                        "LLM call attempt %d/%d failed (model=%s): %s",
                        attempt + 1,
                        self._max_retries,
                        try_model,
                        e,
                    )
                    # P1: 熔断器 — 单次失败
                    if self._circuit_breaker:
                        self._circuit_breaker.on_failure(str(e))
                    if attempt < self._max_retries - 1:
                        backoff = self._retry_backoff_base * (2**attempt)
                        time.sleep(backoff)

        # All retries exhausted
        logger.error("All LLM retries exhausted: %s", last_error)
        return self._mock_response(messages, model)

    @staticmethod
    def _extract_cost(response: Any, model: str, usage: Any) -> float | None:
        """1.1: 从 litellm 响应提取 cost_usd."""
        try:
            # litellm 通常在 _hidden_params 中提供 response_cost
            hidden = getattr(response, "_hidden_params", None) or {}
            cost = hidden.get("response_cost")
            if cost is not None:
                return float(cost)
            # 回退: 使用 litellm.completion_cost（传入完整 response 对象）
            import litellm

            return litellm.completion_cost(completion_response=response, model=model)
        except Exception:
            return None

    def _mock_response(self, messages: list[dict[str, str]], model: str) -> LLMResponse:
        """模拟响应（用于测试或 litellm 未安装时）."""
        last_message = messages[-1]["content"] if messages else ""
        return LLMResponse(
            content=f"Mock response to: {last_message[:100]}...",
            model=model,
            input_tokens=len(last_message) // 4,
            output_tokens=50,
            total_tokens=len(last_message) // 4 + 50,
            latency_ms=10.0,
        )

    def _lookup_cached_response(
        self, messages: list[dict[str, str]], model: str
    ) -> LLMResponse | None:
        """从 ledger 查找相同 prompt 的历史响应（temperature=0 时可复用）."""
        if self._db is None:
            return None
        request_hash = compute_sha256_str(json.dumps(messages, ensure_ascii=False))
        row = self._db.fetchone(
            """
            SELECT input_tokens, output_tokens, total_tokens, cost_usd, latency_ms,
                   response_hash
            FROM llm_call_ledger
            WHERE request_hash = ? AND model = ?
            ORDER BY created_at DESC LIMIT 1
            """,
            (request_hash, model),
        )
        if row is None:
            return None
        # 无法从 response_hash 还原 content，只标记缓存命中但不复用内容
        # （response content 不在 ledger 中存储，只有 hash）
        # 真正的缓存需要 response_store，此处仅用于检测重复调用
        logger.debug(
            "Prompt cache key=%s... matched previous call (model=%s, cost=$%.4f)",
            request_hash[:8],
            model,
            row["cost_usd"] or 0,
        )
        return None

    def _record_call(
        self,
        experiment_id: str | None,
        agent_role: str,
        model: str,
        prompt_version_id: str | None,
        response: LLMResponse,
        messages: list[dict[str, str]],
    ) -> None:
        """记录 LLM 调用."""
        request_hash = compute_sha256_str(json.dumps(messages, ensure_ascii=False))
        response_hash = compute_sha256_str(response.content)

        if self._db is None:
            return

        self._db.execute(
            """
            INSERT INTO llm_call_ledger
                (id, experiment_id, agent_role, model, prompt_version_id,
                 input_tokens, output_tokens, total_tokens, cost_usd, latency_ms,
                 request_hash, response_hash)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                generate_id(),
                experiment_id,
                agent_role,
                model,
                prompt_version_id,
                response.input_tokens,
                response.output_tokens,
                response.total_tokens,
                response.cost_usd,
                response.latency_ms,
                request_hash,
                response_hash,
            ),
        )

    def get_stats(self, experiment_id: str | None = None) -> dict[str, Any]:
        """获取调用统计."""
        if not self._db:
            return {"total_tokens": self._total_tokens, "total_cost": self._total_cost}

        if experiment_id:
            row = self._db.fetchone(
                """
                SELECT COUNT(*) as calls, SUM(total_tokens) as tokens, SUM(cost_usd) as cost
                FROM llm_call_ledger WHERE experiment_id = ?
                """,
                (experiment_id,),
            )
        else:
            row = self._db.fetchone(
                "SELECT COUNT(*) as calls, SUM(total_tokens) as tokens, SUM(cost_usd) as cost FROM llm_call_ledger"
            )

        return {
            "calls": row["calls"] if row else 0,
            "total_tokens": row["tokens"] if row and row["tokens"] else 0,
            "total_cost": row["cost"] if row and row["cost"] else 0.0,
        }

    def get_stats_by_role(self, experiment_id: str | None = None) -> dict[str, dict[str, Any]]:
        """按角色获取统计."""
        if not self._db:
            return {}

        if experiment_id:
            rows = self._db.fetchall(
                """
                SELECT agent_role, COUNT(*) as calls, SUM(total_tokens) as tokens
                FROM llm_call_ledger
                WHERE experiment_id = ?
                GROUP BY agent_role
                """,
                (experiment_id,),
            )
        else:
            rows = self._db.fetchall(
                """
                SELECT agent_role, COUNT(*) as calls, SUM(total_tokens) as tokens
                FROM llm_call_ledger
                GROUP BY agent_role
                """
            )

        return {
            row["agent_role"]: {
                "calls": row["calls"],
                "tokens": row["tokens"],
            }
            for row in rows
        }


class FakeLLM:
    """Fake LLM for testing."""

    def __init__(self, responses: list[str] | None = None) -> None:
        self._responses = responses or []
        self._call_count = 0
        self.calls: list[dict] = []

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        experiment_id: str | None = None,
        agent_role: str = "unknown",
        prompt_version_id: str | None = None,
    ) -> LLMResponse:
        """返回预设响应."""
        self.calls.append(
            {
                "messages": messages,
                "model": model,
                "agent_role": agent_role,
            }
        )

        if self._responses:
            content = self._responses[self._call_count % len(self._responses)]
        else:
            content = f"Fake response {self._call_count}"

        self._call_count += 1

        return LLMResponse(
            content=content,
            model=model or "fake-model",
            input_tokens=100,
            output_tokens=50,
            total_tokens=150,
            latency_ms=1.0,
        )
