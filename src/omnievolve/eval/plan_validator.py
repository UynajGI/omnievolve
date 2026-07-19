"""EvaluationPlan 校验器与 Progressive Evaluation.

S3-05: 实现 EvaluationPlan 校验器
S3-09: 实现 Progressive Evaluation 阶段描述
S3-12: 实现解析失败与异常分类
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import IntEnum

from omnievolve.sandbox.base import CommandSpec, EvaluationPlan, MountSpec

logger = logging.getLogger(__name__)


class PlanValidationError(Exception):
    """评估计划校验错误."""

    pass


class EvaluationStage(IntEnum):
    """渐进式评估阶段.

    S3-09: 任何阶段变化都生成新的 ExecutionEnvironmentVersion。
    """

    STAGE_0_STATIC = 0  # 静态语法 / Patch apply / Compile smoke test
    STAGE_1_SMALL_SAMPLE = 1  # 小样本、短 timeout correctness
    STAGE_2_FULL_CORRECTNESS = 2  # 完整 correctness
    STAGE_3_BENCHMARK = 3  # 正式 benchmark，多次重复与置信区间

    @property
    def timeout_factor(self) -> float:
        """各阶段的超时因子."""
        return {0: 0.1, 1: 0.3, 2: 1.0, 3: 3.0}[self.value]

    @property
    def description(self) -> str:
        """阶段描述."""
        return {
            0: "Static syntax / Patch apply / Compile smoke test",
            1: "Small sample, short timeout correctness",
            2: "Full correctness test suite",
            3: "Formal benchmark with repetitions and confidence intervals",
        }[self.value]


@dataclass
class ProgressiveEvaluationSpec:
    """渐进式评估规格."""

    stages: list[EvaluationStage] = field(
        default_factory=lambda: [
            EvaluationStage.STAGE_0_STATIC,
            EvaluationStage.STAGE_1_SMALL_SAMPLE,
            EvaluationStage.STAGE_2_FULL_CORRECTNESS,
            EvaluationStage.STAGE_3_BENCHMARK,
        ]
    )
    early_exit_on_failure: bool = True
    promotion_threshold: dict[int, float] = field(
        default_factory=lambda: {
            0: 1.0,  # Stage 0 必须通过
            1: 0.8,  # Stage 1 至少 80% 通过
            2: 0.95,  # Stage 2 至少 95% 通过
        }
    )


class EvaluationPlanValidator:
    """评估计划校验器.

    S3-05: 校验 EvaluationPlan 的安全性：
    - 命令安全（无危险操作）
    - 挂载合理（无路径穿越）
    - 资源限制合理
    """

    # 危险命令模式
    DANGEROUS_PATTERNS = [
        "rm -rf /",
        "mkfs",
        "dd if=/dev/zero",
        ":(){ :|:& };:",  # fork bomb
        "chmod 777",
        "/etc/passwd",
        "/etc/shadow",
    ]

    def validate(self, plan: EvaluationPlan) -> None:
        """校验评估计划.

        Raises:
            PlanValidationError: 如果计划不安全或不合理
        """
        self._validate_commands(plan.commands)
        self._validate_mounts(plan.mounts)
        self._validate_resources(plan)

    def _validate_commands(self, commands: list[CommandSpec]) -> None:
        """校验命令安全性."""
        if not commands:
            raise PlanValidationError("No commands in evaluation plan")

        for i, cmd in enumerate(commands):
            # 检查 argv 非空
            if not cmd.argv:
                raise PlanValidationError(f"Command {i} has empty argv")

            # 检查危险模式
            cmd_str = " ".join(cmd.argv)
            for pattern in self.DANGEROUS_PATTERNS:
                if pattern in cmd_str:
                    raise PlanValidationError(f"Command {i} contains dangerous pattern: {pattern}")

            # 检查超时合理
            if cmd.timeout_sec <= 0:
                raise PlanValidationError(f"Command {i} has invalid timeout: {cmd.timeout_sec}")
            if cmd.timeout_sec > 3600:
                logger.warning(f"Command {i} has very long timeout: {cmd.timeout_sec}s")

    def _validate_mounts(self, mounts: list[MountSpec]) -> None:
        """校验挂载安全性."""
        for i, mount in enumerate(mounts):
            # 路径穿越检查
            if ".." in mount.source or ".." in mount.target:
                raise PlanValidationError(
                    f"Mount {i} contains path traversal: {mount.source} -> {mount.target}"
                )

            # 不应挂载敏感路径
            sensitive_paths = ["/etc", "/root", "/var/lib", "/proc", "/sys"]
            for sensitive in sensitive_paths:
                if mount.source.startswith(sensitive):
                    raise PlanValidationError(f"Mount {i} source is sensitive: {mount.source}")

    def _validate_resources(self, plan: EvaluationPlan) -> None:
        """校验资源配置."""
        # network_access 需要显式声明
        if plan.network_access:
            logger.warning("Evaluation plan requests network access - ensure this is intended")


class ResultParseError(Exception):
    """结果解析错误基类."""

    pass


class TimeoutParseError(ResultParseError):
    """超时解析错误."""

    pass


class CrashParseError(ResultParseError):
    """崩溃解析错误."""

    pass


class InvalidOutputParseError(ResultParseError):
    """无效输出解析错误."""

    pass


class ResultParser:
    """结果解析与异常分类.

    S3-12: 实现解析失败与异常分类
    """

    def classify_error(
        self,
        return_codes: list[int],
        stderr: str,
        timed_out: bool,
    ) -> str:
        """分类错误类型.

        Returns:
            错误类型字符串:
            - "timeout": 执行超时
            - "crash": 进程崩溃（segfault 等）
            - "compilation_error": 编译错误
            - "runtime_error": 运行时错误
            - "assertion_error": 断言失败
            - "import_error": 导入失败
            - "syntax_error": 语法错误
            - "unknown": 未知错误
        """
        if timed_out:
            return "timeout"

        # 检查 stderr 中的错误模式
        stderr_lower = stderr.lower()

        if "segmentation fault" in stderr_lower or "sigsegv" in stderr_lower:
            return "crash"

        if "killed" in stderr_lower or "sigkill" in stderr_lower:
            return "crash"

        if "syntaxerror" in stderr_lower:
            return "syntax_error"

        if "importerror" in stderr_lower or "modulenotfounderror" in stderr_lower:
            return "import_error"

        if "compilation error" in stderr_lower or "gcc" in stderr_lower:
            return "compilation_error"

        if "assertionerror" in stderr_lower or "assertion" in stderr_lower:
            return "assertion_error"

        if "runtimeerror" in stderr_lower:
            return "runtime_error"

        # 检查返回码
        if return_codes:
            last_code = return_codes[-1]
            if last_code == -11:  # SIGSEGV
                return "crash"
            if last_code == -9:  # SIGKILL
                return "crash"

        return "unknown"

    def is_retriable(self, error_type: str) -> bool:
        """判断错误是否可重试."""
        # 超时可能是偶发的，可以重试
        # 崩溃通常不可重试（代码有问题）
        retriable = {"timeout", "unknown"}
        return error_type in retriable


def build_progressive_plan(
    base_plan: EvaluationPlan,
    stage: EvaluationStage,
) -> EvaluationPlan:
    """根据阶段构建评估计划.

    S3-09: 不同阶段使用不同的超时和资源配置。
    """
    timeout_factor = stage.timeout_factor

    adjusted_commands = []
    for cmd in base_plan.commands:
        adjusted_cmd = CommandSpec(
            argv=cmd.argv,
            cwd=cmd.cwd,
            timeout_sec=cmd.timeout_sec * timeout_factor,
            env=cmd.env,
        )
        adjusted_commands.append(adjusted_cmd)

    return EvaluationPlan(
        commands=adjusted_commands,
        mounts=base_plan.mounts,
        expected_outputs=base_plan.expected_outputs,
        resource_profile=f"{base_plan.resource_profile}_stage{stage.value}",
        network_access=base_plan.network_access,
    )
