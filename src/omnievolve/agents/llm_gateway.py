"""LLM Gateway - LiteLLM Adapter.

S5-02: 实现 ModelGateway/LiteLLM Adapter
S5-03: 实现 LLMCallLedger
"""

from __future__ import annotations

import json
import logging
import math
import time
from dataclasses import dataclass, field
from typing import Any

from omnievolve.exceptions import (
    LLMAuthenticationError,
    LLMError,
    LLMRateLimitError,
    LLMTimeoutError,
    LLMVerifierCapabilityError,
)
from omnievolve.storage.db import Database
from omnievolve.storage.repositories.base import generate_id
from omnievolve.utils.hashing import compute_sha256_str

logger = logging.getLogger(__name__)


def _token_field(obj: Any, name: str) -> Any:
    """从 dict 或 pydantic 对象（LiteLLM TokenLogprob/TopLogprob）取字段.

    LiteLLM 返回 ``litellm.types.utils.TopLogprob`` / ``TokenLogprob``
    （pydantic 对象，不可下标），测试 fixture 使用 dict；此函数兼容两者。
    """
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


@dataclass(frozen=True)
class LLMEndpoint:
    """One model plus its provider-specific OpenAI-compatible credentials."""

    model: str
    api_key: str | None = field(default=None, repr=False)
    api_base: str | None = None

    def __post_init__(self) -> None:
        if not self.model.strip():
            raise ValueError("LLM endpoint model must not be empty")


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


@dataclass
class TokenScoreResponse:
    """概率 verifier 的 token 级评分响应.

    ``per_position_probabilities`` 保留每个生成位置的完整 top-K 分布，
    供 verifier 层做期望、方差与熵聚合；``probability_coverage`` 是
    实际生成 token 属于评分集合的概率加权比例（缺失概率不补零）。
    """

    content: str
    model: str
    per_position_probabilities: tuple[dict[str, float], ...]
    actual_tokens: tuple[str, ...]
    probability_coverage: float
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cost_usd: float | None = None
    latency_ms: float | None = None
    raw_response: dict = field(default_factory=dict)


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
        fallback_endpoints: list[LLMEndpoint] | None = None,
        circuit_breaker: Any | None = None,
        rate_limiter: Any | None = None,
        budget_guard: Any | None = None,
        request_timeout: float = 120.0,
        default_max_tokens: int = 16384,
        deadline_monotonic: float | None = None,
    ) -> None:
        self._db = db
        self._default_model = default_model
        self._api_key = api_key
        self._api_base = api_base
        self._max_retries = max_retries
        self._retry_backoff_base = retry_backoff_base
        self._fallback_model = fallback_model
        self._fallback_endpoints = tuple(fallback_endpoints or ())
        # Avoid paying the same permanent provider/model failure on every role
        # call. These sets are process-local and intentionally never serialized.
        self._disabled_credentials: set[tuple[str | None, str | None]] = set()
        self._disabled_endpoints: set[tuple[str, str | None, str | None]] = set()
        self._total_tokens = 0
        self._total_cost = 0.0
        self._cost_known = True
        # P1: 熔断器 + 限流
        self._circuit_breaker = circuit_breaker
        self._rate_limiter = rate_limiter
        # 1.1: BudgetGuard — LLM token 消耗传播到预算系统
        self._budget_guard = budget_guard
        # 网络超时保护（秒），防止 API 无响应时线程永久挂起
        self._request_timeout = request_timeout
        # 默认最大输出 token 数（可被 chat() 调用方覆盖）
        self._default_max_tokens = default_max_tokens
        # Optional hard wall deadline used by isolated policy-canary arms.
        # Unlike BudgetGuard, this is consumed while an HTTP request is active.
        self._deadline_monotonic = deadline_monotonic

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
        # 未显式指定时用网关默认上限（推理模型需充足预算）
        max_tokens = max_tokens if max_tokens is not None else self._default_max_tokens
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
        self._remaining_deadline(raise_if_expired=True)

        # S5-10: retry/backoff/fallback
        last_error: Exception | None = None
        endpoints_to_try = [LLMEndpoint(model, self._api_key, self._api_base)]
        if self._fallback_model and self._fallback_model != model:
            endpoints_to_try.append(
                LLMEndpoint(self._fallback_model, self._api_key, self._api_base)
            )
        endpoints_to_try.extend(
            endpoint for endpoint in self._fallback_endpoints if endpoint.model != model
        )

        failed_credentials: set[tuple[str | None, str | None]] = set()
        for endpoint_index, endpoint in enumerate(endpoints_to_try):
            credential_id = (endpoint.api_key, endpoint.api_base)
            endpoint_id = (endpoint.model, endpoint.api_key, endpoint.api_base)
            if (
                credential_id in failed_credentials
                or credential_id in self._disabled_credentials
                or endpoint_id in self._disabled_endpoints
            ):
                continue
            try_model = endpoint.model
            provider_model = self._provider_model(try_model, endpoint.api_base)
            for attempt in range(self._max_retries):
                try:
                    import litellm

                    remaining = self._remaining_deadline(raise_if_expired=True)
                    request_timeout = (
                        self._request_timeout
                        if remaining is None
                        else min(self._request_timeout, max(0.001, remaining))
                    )
                    response = litellm.completion(
                        model=provider_model,
                        messages=messages,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        api_key=endpoint.api_key,
                        api_base=endpoint.api_base,
                        timeout=request_timeout,
                        # OmniEvolve owns retries, backoff, fallback, deadlines,
                        # and attempt provenance. Hidden SDK retries would make
                        # one recorded attempt exceed its wall-clock budget.
                        num_retries=0,
                    )

                    latency_ms = (time.time() - start_time) * 1000
                    content = response.choices[0].message.content or ""
                    if not content.strip():
                        raise RuntimeError(
                            f"Provider returned an empty final response for model {try_model}"
                        )
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
                    if llm_response.cost_usd is not None:
                        self._total_cost += llm_response.cost_usd
                    else:
                        self._cost_known = False

                    # 1.1: 传播 LLM token 消耗到 BudgetGuard
                    if self._budget_guard:
                        self._budget_guard.consume(
                            model=try_model,
                            input_tokens=llm_response.input_tokens,
                            output_tokens=llm_response.output_tokens,
                            compute_sec=0.0,
                            cost_usd=llm_response.cost_usd,
                            cost_known=llm_response.cost_usd is not None,
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

                except ImportError as exc:
                    logger.error("litellm is required for real LLM execution")
                    if self._circuit_breaker:
                        self._circuit_breaker.on_failure("litellm not installed")
                    raise LLMError(
                        "litellm is not installed; use FakeLLM explicitly for tests"
                    ) from exc
                except LLMTimeoutError:
                    raise
                except Exception as e:
                    last_error = e
                    safe_error = self._redact_error(e)
                    logger.warning(
                        "LLM call attempt %d/%d failed (model=%s): %s",
                        attempt + 1,
                        self._max_retries,
                        try_model,
                        safe_error,
                    )
                    # P1: 熔断器 — 单次失败
                    if self._circuit_breaker:
                        self._circuit_breaker.on_failure(safe_error)
                    if self._is_authentication_error(e):
                        failed_credentials.add(credential_id)
                        self._disabled_credentials.add(credential_id)
                        has_distinct_fallback = any(
                            (candidate.api_key, candidate.api_base) not in failed_credentials
                            for candidate in endpoints_to_try[endpoint_index + 1 :]
                        )
                        if has_distinct_fallback:
                            logger.warning(
                                "Authentication failed for model=%s; trying next configured endpoint",
                                try_model,
                            )
                            break
                        raise LLMAuthenticationError(safe_error) from e
                    if self._is_permanent_endpoint_error(e):
                        self._disabled_endpoints.add(endpoint_id)
                        if endpoint_index < len(endpoints_to_try) - 1:
                            logger.warning(
                                "Permanent provider/model failure for model=%s; "
                                "trying next configured endpoint",
                                try_model,
                            )
                            break
                        raise self._typed_error(e, safe_error) from e
                    self._remaining_deadline(raise_if_expired=True, cause=e)
                    if attempt < self._max_retries - 1:
                        backoff = self._retry_backoff_base * (2**attempt)
                        remaining = self._remaining_deadline(raise_if_expired=True)
                        if remaining is not None:
                            backoff = min(backoff, remaining)
                        time.sleep(backoff)

        # All retries exhausted
        if last_error is None:
            raise LLMError("LLM gateway did not execute any request")
        safe_error = self._redact_error(last_error)
        logger.error("All LLM retries exhausted: %s", safe_error)
        raise self._typed_error(last_error, safe_error) from last_error

    def score_tokens(
        self,
        messages: list[dict[str, str]],
        *,
        score_tokens: tuple[str, ...],
        model: str,
        top_logprobs: int,
        experiment_id: str | None,
        prompt_version_id: str | None,
        granularity: int = 1,
        temperature: float = 0.0,
        max_retries: int | None = None,
        endpoints: list[LLMEndpoint] | None = None,
    ) -> TokenScoreResponse:
        """概率 verifier 专用 token 评分调用.

        与 ``chat()`` 隔离，避免污染普通 agent 调用语义：

        - 请求 ``logprobs=True`` 与显式 ``top_logprobs``，禁止 ``drop_params``；
        - provider 不支持 / 参数被静默丢弃时抛 ``LLMVerifierCapabilityError``；
        - 校验评分标签能以单 token 形式生成；
        - 缺失 token 概率不补零、不无条件重归一化；
        - fallback 只切换到调用方传入的 ``endpoints``（必须已通过
          capability probe 的 endpoint 集合）；
        - 以 ``agent_role="verifier"`` 进入 LLM ledger；
        - retry、deadline 与 attempt provenance 仍由 OmniEvolve 管理。

        Returns:
            TokenScoreResponse — 每个生成位置的完整 top-K 概率分布。
        """
        if not score_tokens:
            raise ValueError("score_tokens must not be empty")
        if top_logprobs < 1:
            raise ValueError("top_logprobs must be at least 1")
        if granularity < 1:
            raise ValueError("granularity must be positive")
        if model is None or not model.strip():
            model = self._default_model

        start_time = time.time()
        if self._circuit_breaker and not self._circuit_breaker.can_execute():
            raise RuntimeError(
                "LLM gateway circuit breaker is OPEN. "
                "All requests are rejected to protect cost/availability."
            )
        if self._rate_limiter:
            waited = self._rate_limiter.acquire()
            if waited > 0:
                logger.debug("Rate limiter waited %.1fs", waited)
        self._remaining_deadline(raise_if_expired=True)

        endpoints_to_try = (
            endpoints
            if endpoints is not None
            else [LLMEndpoint(model, self._api_key, self._api_base)]
        )
        last_error: Exception | None = None
        for endpoint_index, endpoint in enumerate(endpoints_to_try):
            endpoint_id = (endpoint.model, endpoint.api_key, endpoint.api_base)
            if endpoint_id in self._disabled_endpoints:
                continue
            try_model = endpoint.model
            provider_model = self._provider_model(try_model, endpoint.api_base)
            for attempt in range(max_retries if max_retries is not None else self._max_retries):
                try:
                    import litellm

                    remaining = self._remaining_deadline(raise_if_expired=True)
                    request_timeout = (
                        self._request_timeout
                        if remaining is None
                        else min(self._request_timeout, max(0.001, remaining))
                    )
                    response = litellm.completion(
                        model=provider_model,
                        messages=messages,
                        temperature=temperature,
                        max_tokens=granularity,
                        logprobs=True,
                        top_logprobs=top_logprobs,
                        # 参数必须被 provider 接受；静默丢弃 = capability failure。
                        drop_params=False,
                        api_key=endpoint.api_key,
                        api_base=endpoint.api_base,
                        timeout=request_timeout,
                        num_retries=0,
                    )

                    latency_ms = (time.time() - start_time) * 1000
                    content = response.choices[0].message.content or ""
                    usage = response.usage

                    logprobs = getattr(response.choices[0], "logprobs", None)
                    if logprobs is None or not getattr(logprobs, "content", None):
                        raise LLMVerifierCapabilityError(
                            f"Provider {try_model} ignored logprobs request"
                        )
                    positions: list[tuple[str, dict[str, float]]] = []
                    score_token_seen = False
                    for item in logprobs.content:
                        top = _token_field(item, "top_logprobs")
                        if top is None or not top:
                            raise LLMVerifierCapabilityError(
                                f"Provider {try_model} silently dropped top_logprobs"
                            )
                        distribution: dict[str, float] = {}
                        for entry in top:
                            token = _token_field(entry, "token")
                            logprob = _token_field(entry, "logprob")
                            if token is None or logprob is None:
                                continue
                            distribution[str(token)] = math.exp(float(logprob))
                        actual = str(_token_field(item, "token") or "")
                        positions.append((actual, distribution))
                        if actual in score_tokens or any(
                            token in distribution for token in score_tokens
                        ):
                            score_token_seen = True

                    if not positions:
                        raise LLMVerifierCapabilityError(
                            f"Provider {try_model} returned no generated tokens"
                        )
                    if not score_token_seen:
                        # 没有任何位置能生成评分标签 → tokenizer 无法单 token 生成。
                        raise LLMVerifierCapabilityError(
                            f"Provider {try_model} cannot emit any score token from "
                            f"{score_tokens} as single tokens"
                        )

                    # 评分覆盖率 = 评分 token 集合在已知 top-K 分布上的概率质量比例
                    # （不是只取"实际生成 token"自身的概率）。
                    coverage = sum(
                        sum(
                            probability
                            for token, probability in distribution.items()
                            if token in score_tokens
                        )
                        for _, distribution in positions
                    ) / len(positions)

                    token_response = TokenScoreResponse(
                        content=content,
                        model=try_model,
                        per_position_probabilities=tuple(
                            distribution for _, distribution in positions
                        ),
                        actual_tokens=tuple(actual for actual, _ in positions),
                        probability_coverage=coverage,
                        input_tokens=usage.prompt_tokens if usage else 0,
                        output_tokens=usage.completion_tokens if usage else 0,
                        total_tokens=usage.total_tokens if usage else 0,
                        cost_usd=self._extract_cost(response, try_model, usage),
                        latency_ms=latency_ms,
                        raw_response=response.model_dump()
                        if hasattr(response, "model_dump")
                        else {},
                    )

                    self._total_tokens += token_response.total_tokens
                    if token_response.cost_usd is not None:
                        self._total_cost += token_response.cost_usd
                    else:
                        self._cost_known = False

                    if self._budget_guard:
                        self._budget_guard.consume(
                            model=try_model,
                            input_tokens=token_response.input_tokens,
                            output_tokens=token_response.output_tokens,
                            compute_sec=0.0,
                            cost_usd=token_response.cost_usd,
                            cost_known=token_response.cost_usd is not None,
                        )

                    if self._circuit_breaker:
                        self._circuit_breaker.on_success()

                    if self._db:
                        self._record_call(
                            experiment_id=experiment_id,
                            agent_role="verifier",
                            model=try_model,
                            prompt_version_id=prompt_version_id,
                            response=LLMResponse(
                                content=content,
                                model=try_model,
                                input_tokens=token_response.input_tokens,
                                output_tokens=token_response.output_tokens,
                                total_tokens=token_response.total_tokens,
                                cost_usd=token_response.cost_usd,
                                latency_ms=latency_ms,
                                raw_response=token_response.raw_response,
                            ),
                            messages=messages,
                        )

                    return token_response

                except LLMVerifierCapabilityError:
                    raise
                except ImportError as exc:
                    logger.error("litellm is required for real LLM execution")
                    if self._circuit_breaker:
                        self._circuit_breaker.on_failure("litellm not installed")
                    raise LLMError(
                        "litellm is not installed; use FakeLLM explicitly for tests"
                    ) from exc
                except LLMTimeoutError:
                    raise
                except Exception as e:
                    last_error = e
                    safe_error = self._redact_error(e)
                    logger.warning(
                        "Verifier token call attempt %d/%d failed (model=%s): %s",
                        attempt + 1,
                        max_retries if max_retries is not None else self._max_retries,
                        try_model,
                        safe_error,
                    )
                    if self._circuit_breaker:
                        self._circuit_breaker.on_failure(safe_error)
                    if self._is_authentication_error(e):
                        self._disabled_endpoints.add(endpoint_id)
                        if endpoint_index < len(endpoints_to_try) - 1:
                            break
                        raise LLMAuthenticationError(safe_error) from e
                    if self._is_permanent_endpoint_error(e) or self._is_logprobs_error(e):
                        self._disabled_endpoints.add(endpoint_id)
                        if endpoint_index < len(endpoints_to_try) - 1:
                            logger.warning(
                                "Permanent verifier failure for model=%s; "
                                "trying next probed endpoint",
                                try_model,
                            )
                            break
                        if self._is_logprobs_error(e):
                            raise LLMVerifierCapabilityError(safe_error) from e
                        raise self._typed_error(e, safe_error) from e
                    self._remaining_deadline(raise_if_expired=True, cause=e)
                    if (
                        attempt
                        < (max_retries if max_retries is not None else self._max_retries) - 1
                    ):
                        backoff = self._retry_backoff_base * (2**attempt)
                        remaining = self._remaining_deadline(raise_if_expired=True)
                        if remaining is not None:
                            backoff = min(backoff, remaining)
                        time.sleep(backoff)

        if last_error is None:
            raise LLMError("LLM gateway did not execute any verifier request")
        safe_error = self._redact_error(last_error)
        logger.error("All verifier retries exhausted: %s", safe_error)
        raise self._typed_error(last_error, safe_error) from last_error

    @staticmethod
    def _is_logprobs_error(error: Exception) -> bool:
        """参数被拒绝（logprobs/top_logprobs 不支持）→ 能力失败."""
        text = f"{type(error).__name__}: {error}".lower()
        return any(
            marker in text
            for marker in ("logprobs", "top_logprobs", "log_probs", "unsupported parameter")
        )

    @staticmethod
    def _provider_model(model: str, api_base: str | None) -> str:
        """Tell LiteLLM to use its OpenAI-compatible adapter for custom bases."""

        if api_base and "/" not in model:
            return f"openai/{model}"
        return model

    def fork(
        self,
        db: Database | None = None,
        *,
        deadline_monotonic: float | None = None,
        max_retries: int | None = None,
        request_timeout: float | None = None,
    ) -> LLMGateway:
        """Create an independent accounting/retry context for a canary arm."""
        return LLMGateway(
            db,
            default_model=self._default_model,
            api_key=self._api_key,
            api_base=self._api_base,
            max_retries=self._max_retries if max_retries is None else max_retries,
            retry_backoff_base=self._retry_backoff_base,
            fallback_model=self._fallback_model,
            fallback_endpoints=list(self._fallback_endpoints),
            request_timeout=(self._request_timeout if request_timeout is None else request_timeout),
            default_max_tokens=self._default_max_tokens,
            deadline_monotonic=deadline_monotonic,
        )

    def _remaining_deadline(
        self,
        *,
        raise_if_expired: bool = False,
        cause: Exception | None = None,
    ) -> float | None:
        if self._deadline_monotonic is None:
            return None
        remaining = self._deadline_monotonic - time.monotonic()
        if raise_if_expired and remaining <= 0:
            error = LLMTimeoutError("LLM gateway hard deadline exceeded")
            if cause is not None:
                raise error from cause
            raise error
        return remaining

    def _redact_error(self, error: Exception) -> str:
        """Return an error message safe for logs and persisted job diagnostics."""
        message = str(error)
        api_keys = [self._api_key, *(endpoint.api_key for endpoint in self._fallback_endpoints)]
        for api_key in api_keys:
            if api_key:
                message = message.replace(api_key, "[REDACTED]")
        return message

    @staticmethod
    def _status_code(error: Exception) -> int | None:
        """Extract an HTTP status code from common SDK exception shapes."""
        status = getattr(error, "status_code", None)
        if status is None:
            status = getattr(getattr(error, "response", None), "status_code", None)
        try:
            return int(status) if status is not None else None
        except (TypeError, ValueError):
            return None

    @classmethod
    def _is_authentication_error(cls, error: Exception) -> bool:
        """Authentication failures are permanent for a run and must not be retried."""
        text = f"{type(error).__name__}: {error}".lower()
        return cls._status_code(error) == 401 or any(
            marker in text
            for marker in (
                "authentication",
                "invalid api key",
                "invalid_key",
                "unauthorized",
            )
        )

    @classmethod
    def _is_permanent_endpoint_error(cls, error: Exception) -> bool:
        """Errors that retries cannot fix but a distinct provider may."""
        status = cls._status_code(error)
        text = f"{type(error).__name__}: {error}".lower()
        return status in {400, 403, 404} or any(
            marker in text
            for marker in (
                "model access denied",
                "model not found",
                "does not exist",
                "permission denied",
            )
        )

    @classmethod
    def _typed_error(cls, error: Exception, message: str) -> LLMError:
        """Map provider errors to the public typed exception hierarchy."""
        status = cls._status_code(error)
        name = type(error).__name__.lower()
        text = message.lower()
        if cls._is_authentication_error(error):
            return LLMAuthenticationError(message)
        if status == 429 or "ratelimit" in name or "rate limit" in text:
            return LLMRateLimitError(message)
        if isinstance(error, TimeoutError) or "timeout" in name or "timed out" in text:
            return LLMTimeoutError(message)
        return LLMError(message)

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
            return {
                "total_tokens": self._total_tokens,
                "total_cost": self._total_cost if self._cost_known else None,
                "known_cost": self._total_cost,
                "cost_known": self._cost_known,
            }

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

        calls = row["calls"] if row else 0
        priced_row = self._db.fetchone(
            (
                "SELECT COUNT(cost_usd) AS priced FROM llm_call_ledger WHERE experiment_id = ?"
                if experiment_id
                else "SELECT COUNT(cost_usd) AS priced FROM llm_call_ledger"
            ),
            (experiment_id,) if experiment_id else (),
        )
        priced = priced_row["priced"] if priced_row else 0
        cost_known = calls == priced
        known_cost = float(row["cost"] or 0.0) if row else 0.0
        return {
            "calls": calls,
            "total_tokens": row["tokens"] if row and row["tokens"] else 0,
            "total_cost": known_cost if cost_known else None,
            "known_cost": known_cost,
            "cost_known": cost_known,
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

    def __init__(
        self,
        responses: list[str] | None = None,
        *,
        score_token_probabilities: dict[str, float] | None = None,
    ) -> None:
        self._responses = responses or []
        self._call_count = 0
        self.calls: list[dict] = []
        # 概率 verifier fixture：评分 token → 概率（缺失时确定性生成）。
        self._score_token_probabilities = score_token_probabilities

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

    def score_tokens(
        self,
        messages: list[dict[str, str]],
        *,
        score_tokens: tuple[str, ...],
        model: str,
        top_logprobs: int,
        experiment_id: str,
        prompt_version_id: str,
        granularity: int = 1,
        temperature: float = 0.0,
        max_retries: int | None = None,
        endpoints: list | None = None,
    ) -> TokenScoreResponse:
        """确定性 token 评分：概率来自 fixture 或 request hash 播种的生成器."""
        import random

        del top_logprobs, experiment_id, prompt_version_id, max_retries, endpoints
        self.calls.append({"messages": messages, "model": model, "agent_role": "verifier"})
        seed = compute_sha256_str(
            json.dumps(messages, ensure_ascii=False, sort_keys=True) + str(granularity)
        )
        probabilities = self._score_token_probabilities
        if probabilities is None:
            rng = random.Random(seed)
            probabilities = {token: rng.random() + 0.01 for token in score_tokens}
            total = sum(probabilities.values())
            probabilities = {token: p / total for token, p in probabilities.items()}
        positions: list[dict[str, float]] = []
        actual_tokens: list[str] = []
        total_actual = 0.0
        token_list = list(probabilities.keys())
        weights = list(probabilities.values())
        for index in range(granularity):
            # temperature=0（评分默认）取 argmax，保证 coverage 稳定；
            # 否则按概率加权采样。
            if temperature == 0.0:
                chosen = max(probabilities, key=lambda token: probabilities[token])
            else:
                rng = random.Random(f"{seed}:{index}")
                chosen = rng.choices(token_list, weights=weights, k=1)[0]
            actual_tokens.append(chosen)
            distribution = dict(probabilities)
            total_actual += probabilities.get(chosen, 0.0)
            positions.append(distribution)
        coverage = total_actual / granularity if granularity else 0.0
        return TokenScoreResponse(
            content="".join(actual_tokens),
            model=model or "fake-model",
            per_position_probabilities=tuple(positions),
            actual_tokens=tuple(actual_tokens),
            probability_coverage=coverage,
            input_tokens=100,
            output_tokens=granularity,
            total_tokens=100 + granularity,
            latency_ms=1.0,
        )

    def fork(
        self,
        db: Database | None = None,
        **_: Any,
    ) -> FakeLLM:
        """Return a fresh deterministic stream for independent replay arms."""
        del db
        return FakeLLM(
            list(self._responses), score_token_probabilities=self._score_token_probabilities
        )
