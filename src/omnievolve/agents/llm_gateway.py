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
                        latency_ms=latency_ms,
                        raw_response=response.model_dump()
                        if hasattr(response, "model_dump")
                        else {},
                    )

                    self._total_tokens += llm_response.total_tokens

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
                    if attempt < self._max_retries - 1:
                        backoff = self._retry_backoff_base * (2**attempt)
                        time.sleep(backoff)

        # All retries exhausted
        logger.error("All LLM retries exhausted: %s", last_error)
        return self._mock_response(messages, model)

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
