"""SandboxBackend 协议与数据结构.

S2-01: 冻结 SandboxBackend 协议与数据结构
- ExecutionPlan、SandboxResult、mount/env/resource policy 职责清晰
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class MountSpec:
    """挂载规格."""

    source: str
    target: str
    read_only: bool = True


@dataclass(frozen=True)
class CommandSpec:
    """命令规格."""

    argv: list[str]
    cwd: str = "/workspace"
    timeout_sec: float = 30.0
    env: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class EvaluationPlan:
    """评估计划 - 由 TaskEvaluator 构造，Sandbox 执行.

    Evaluator 只能声明评估计划，不能绕过 Sandbox 直接执行候选代码。
    """

    commands: list[CommandSpec]
    mounts: list[MountSpec] = field(default_factory=list)
    expected_outputs: list[str] = field(default_factory=list)
    resource_profile: str = "default"
    network_access: bool = False


@dataclass(frozen=True)
class SandboxPolicy:
    """沙箱安全策略."""

    timeout_sec: float = 30.0
    mem_limit_mb: int = 512
    cpu_limit: float = 1.0
    pids_limit: int = 64
    network_mode: str = "none"  # none / bridge / host
    read_only_root: bool = True
    run_as_non_root: bool = True
    drop_capabilities: bool = True
    no_new_privileges: bool = True
    tmpfs_mb: int = 256
    allowed_env: set[str] = field(default_factory=set)


@dataclass(frozen=True)
class SandboxExecutionResult:
    """沙箱执行结果."""

    return_codes: list[int]
    stdout: str
    stderr: str
    output_artifacts: dict[str, str]  # path -> artifact hash
    execution_time_ms: float
    cpu_time_ms: float
    memory_peak_kb: int
    timed_out: bool = False
    policy_violation: str | None = None


@dataclass(frozen=True)
class CandidateArtifact:
    """候选 Artifact 信息."""

    candidate_id: str
    source_hash: str
    manifest_hash: str | None
    language: str
    entrypoint: str | None = None


@runtime_checkable
class SandboxBackend(Protocol):
    """沙箱执行后端协议.

    所有执行后端必须实现此协议。
    """

    @property
    def environment_version_id(self) -> str:
        """执行环境版本 ID."""
        ...

    def execute(
        self,
        plan: EvaluationPlan,
        candidate: CandidateArtifact,
        policy: SandboxPolicy,
    ) -> SandboxExecutionResult:
        """执行评估计划.

        Args:
            plan: 评估计划（命令、挂载、预期输出）
            candidate: 候选 Artifact 信息
            policy: 安全策略

        Returns:
            执行结果
        """
        ...

    def healthcheck(self) -> dict:
        """健康检查.

        Returns:
            健康状态字典
        """
        ...


class SandboxError(Exception):
    """沙箱执行错误基类."""

    pass


class SandboxTimeoutError(SandboxError):
    """执行超时."""

    pass


class SandboxPolicyViolationError(SandboxError):
    """策略违规."""

    pass


class SandboxSetupError(SandboxError):
    """沙箱设置错误."""

    pass
