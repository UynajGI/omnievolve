"""类型化异常层次.

参考 OpenEvolve/ShinkaEvolve 最佳实践：细化异常类型，取代宽泛的
`except Exception` 捕获，使调用方可以精确处理可恢复的错误。

层次结构:
    OmniEvolveError
    ├── EvolutionError          — 进化过程错误（可恢复）
    ├── SandboxError            — 沙箱执行错误
    │   ├── SandboxTimeoutError
    │   └── SandboxSecurityError
    ├── EvaluatorError          — 评估器错误
    ├── LLMError                — LLM 调用错误
    │   ├── LLMTimeoutError
    │   ├── LLMRateLimitError
    │   └── LLMAuthenticationError
    ├── StorageError            — 存储层错误
    └── ConfigurationError      — 配置错误（不可恢复）
"""

from __future__ import annotations


class OmniEvolveError(Exception):
    """所有 OmniEvolve 异常的基类."""


# ── 进化 ──────────────────────────────────────────────────────────────


class EvolutionError(OmniEvolveError):
    """进化过程中的可恢复错误.

    用于 individual candidate 生成失败等可重试场景.
    """


# ── 沙箱 ──────────────────────────────────────────────────────────────


class SandboxError(OmniEvolveError):
    """沙箱执行错误."""


class SandboxTimeoutError(SandboxError):
    """沙箱执行超时."""


class SandboxSecurityError(SandboxError):
    """沙箱安全策略违规."""


# ── 评估器 ────────────────────────────────────────────────────────────


class EvaluatorError(OmniEvolveError):
    """评估器错误."""


# ── LLM ───────────────────────────────────────────────────────────────


class LLMError(OmniEvolveError):
    """LLM 调用错误."""


class LLMTimeoutError(LLMError):
    """LLM 调用超时（可重试）."""


class LLMRateLimitError(LLMError):
    """LLM 速率限制（应退避重试）."""


class LLMAuthenticationError(LLMError):
    """LLM 认证失败（不可重试）."""


# ── 存储 ──────────────────────────────────────────────────────────────


class StorageError(OmniEvolveError):
    """存储层错误."""


# ── 配置 ──────────────────────────────────────────────────────────────


class ConfigurationError(OmniEvolveError):
    """配置错误（通常在启动时不可恢复）."""
