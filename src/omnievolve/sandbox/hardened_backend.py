"""Hardened 执行后端 Adapter.

S2: 可接 gVisor、nsjail、Firecracker、E2B、Modal 等实现

这是一个占位实现，实际使用时需要替换为具体的强隔离后端。

TODO(延后): 实现至少一个具体的强隔离后端（推荐 nsjail 或 gVisor），
            包括镜像构建、资源限制、网络隔离、文件系统只读挂载。
"""

from __future__ import annotations

from typing import Any

from omnievolve.sandbox.base import (
    CandidateArtifact,
    EvaluationPlan,
    SandboxExecutionResult,
    SandboxPolicy,
    SandboxSetupError,
)


class HardenedBackend:
    """强隔离执行后端 Adapter.

    可接入：
    - gVisor
    - nsjail
    - Firecracker
    - E2B
    - Modal
    - 其他强隔离实现

    当前为占位实现，需要用户自行扩展。
    """

    def __init__(self, provider: str = "generic", **config: Any) -> None:
        """初始化强隔离后端.

        Args:
            provider: 提供商名称 (gvisor/nsjail/firecracker/e2b/modal)
            **config: 提供商特定配置
        """
        self._provider = provider
        self._config = config
        self._environment_version_id = f"hardened-{provider}"

    @property
    def environment_version_id(self) -> str:
        return self._environment_version_id

    def execute(
        self,
        plan: EvaluationPlan,
        candidate: CandidateArtifact,
        policy: SandboxPolicy,
    ) -> SandboxExecutionResult:
        """执行评估计划.

        需要由具体实现覆盖。
        """
        raise SandboxSetupError(
            f"HardenedBackend provider '{self._provider}' is not implemented. "
            "Please implement a concrete hardened backend or use DockerBackend."
        )

    def healthcheck(self) -> dict:
        """健康检查."""
        return {
            "status": "unhealthy",
            "provider": self._provider,
            "error": "HardenedBackend is a placeholder. Implement a concrete provider.",
        }
