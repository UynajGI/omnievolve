"""Provider capability probe — 概率 verifier 启用前只读探测.

集成计划 §7：现有 GLM/Qwen endpoint 必须经过 probe，不能根据
OpenAI-compatible 标签推断 logprobs 支持性。

结果分三类:
- ``native_logprobs``: 可原生运行论文公式；
- ``two_stage_required``: 生成模型不支持，但存在可用的独立 verifier；
- ``unsupported``: 禁止启用 live verifier。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Literal

from omnievolve.agents.llm_gateway import LLMGateway
from omnievolve.exceptions import LLMVerifierCapabilityError

ProbeStatus = Literal["native_logprobs", "two_stage_required", "unsupported"]

_DEFAULT_PROBE_TOKENS = tuple(str(value) for value in range(0, 21))


@dataclass(frozen=True)
class CapabilityProbeResult:
    """单 endpoint 的能力探测结果."""

    status: ProbeStatus
    model: str
    max_top_logprobs: int
    probability_coverage: float
    capability_hash: str
    endpoint_fingerprint: str
    error: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "model": self.model,
            "max_top_logprobs": self.max_top_logprobs,
            "probability_coverage": self.probability_coverage,
            "capability_hash": self.capability_hash,
            "endpoint_fingerprint": self.endpoint_fingerprint,
            "error": self.error,
        }


def _endpoint_fingerprint(model: str, api_base: str | None) -> str:
    return hashlib.sha256(
        json.dumps({"model": model, "api_base": api_base}, sort_keys=True).encode("utf-8")
    ).hexdigest()


def compute_capability_hash(
    *,
    model: str,
    api_base: str | None,
    max_top_logprobs: int,
    probability_coverage: float,
) -> str:
    """稳定能力哈希：进入 verification_batch 供 checkpoint/replay 比对."""
    return hashlib.sha256(
        json.dumps(
            {
                "model": model,
                "api_base": api_base,
                "max_top_logprobs": max_top_logprobs,
                "probability_coverage": round(probability_coverage, 6),
            },
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


class VerifierCapabilityProbe:
    """执行只读 probe 并记录 capability hash.

    probe 使用固定无业务内容的 prompt，不消耗 verifier 预算语义；
    失败分类：``LLMVerifierCapabilityError`` → unsupported，
    鉴权/超时等环境错误向上传播（不等于能力不支持）。
    """

    def __init__(
        self,
        gateway: LLMGateway,
        *,
        score_tokens: tuple[str, ...] = _DEFAULT_PROBE_TOKENS,
        probe_top_logprobs: tuple[int, ...] = (5, 20),
    ) -> None:
        self._gateway = gateway
        self._score_tokens = score_tokens
        self._probe_top_logprobs = tuple(probe_top_logprobs)

    def probe(
        self,
        model: str,
        *,
        api_key: str | None = None,
        api_base: str | None = None,
        experiment_id: str | None = None,
        prompt_version_id: str | None = None,
    ) -> CapabilityProbeResult:
        """对单个 model/endpoint 执行能力探测."""
        from omnievolve.agents.llm_gateway import LLMEndpoint

        endpoint = LLMEndpoint(model, api_key, api_base)
        messages = [
            {
                "role": "user",
                "content": (
                    "You are a scoring assistant. Rate the following text on a "
                    "scale from 0 to 20. Respond with a single number only.\n"
                    "Text: hello world"
                ),
            }
        ]
        coverage = 0.0
        max_top_logprobs = 0
        last_error = ""
        for top_logprobs in self._probe_top_logprobs:
            try:
                response = self._gateway.score_tokens(
                    messages,
                    score_tokens=self._score_tokens,
                    model=model,
                    top_logprobs=top_logprobs,
                    experiment_id=experiment_id,
                    prompt_version_id=prompt_version_id,
                    granularity=1,
                    max_retries=1,
                    endpoints=[endpoint],
                )
                coverage = max(coverage, response.probability_coverage)
                max_top_logprobs = max(max_top_logprobs, top_logprobs)
            except LLMVerifierCapabilityError as exc:
                last_error = str(exc)
                break
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                break

        if max_top_logprobs == 0:
            return CapabilityProbeResult(
                status="unsupported",
                model=model,
                max_top_logprobs=0,
                probability_coverage=0.0,
                capability_hash=compute_capability_hash(
                    model=model,
                    api_base=api_base,
                    max_top_logprobs=0,
                    probability_coverage=0.0,
                ),
                endpoint_fingerprint=_endpoint_fingerprint(model, api_base),
                error=last_error,
            )

        # 第一轮只支持原生 logprobs；two_stage_required 保留为扩展位。
        status: ProbeStatus = "native_logprobs"
        return CapabilityProbeResult(
            status=status,
            model=model,
            max_top_logprobs=max_top_logprobs,
            probability_coverage=coverage,
            capability_hash=compute_capability_hash(
                model=model,
                api_base=api_base,
                max_top_logprobs=max_top_logprobs,
                probability_coverage=coverage,
            ),
            endpoint_fingerprint=_endpoint_fingerprint(model, api_base),
            error=last_error,
        )


__all__ = [
    "CapabilityProbeResult",
    "VerifierCapabilityProbe",
    "compute_capability_hash",
    "_DEFAULT_PROBE_TOKENS",
]
