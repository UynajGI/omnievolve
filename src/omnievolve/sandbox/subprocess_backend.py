"""Trusted Subprocess 执行后端.

S2-13: 实现 TrustedSubprocessBackend
- 必须显式 trusted=true
- 警告清晰
- 不误称安全沙箱

仅供用户明确确认的可信代码、本地单元测试或开发调试。
resource.setrlimit 仅在支持的平台上限制部分资源，
不提供文件系统、网络、权限或系统调用隔离。
"""

from __future__ import annotations

import logging
import os
import resource
import subprocess
import tempfile
import time
import uuid
import warnings
from pathlib import Path
from typing import Any

from omnievolve.sandbox.base import (
    CandidateArtifact,
    EvaluationPlan,
    SandboxExecutionResult,
    SandboxPolicy,
)

logger = logging.getLogger(__name__)


class TrustedSubprocessBackend:
    """Trusted Subprocess 执行后端.

    警告：此后端不提供真正的安全隔离！

    仅用于：
    - 用户明确确认的可信代码
    - 本地单元测试
    - 开发调试

    安全限制：
    - 使用 resource.setrlimit 限制部分资源（仅 Unix）
    - 不提供文件系统隔离
    - 不提供网络隔离
    - 不提供权限隔离
    """

    def __init__(
        self,
        *,
        work_dir: str | Path | None = None,
        artifact_store: Any = None,
        trusted: bool = False,
    ) -> None:
        """初始化 Trusted Subprocess 后端.

        Args:
            work_dir: 工作目录
            artifact_store: ArtifactStore 实例
            trusted: 必须显式设置为 True 才能使用
        """
        if not trusted:
            raise ValueError(
                "TrustedSubprocessBackend requires explicit trusted=True. "
                "This backend does NOT provide security isolation. "
                "Only use for trusted code, local testing, or development."
            )

        warnings.warn(
            "TrustedSubprocessBackend does NOT provide security isolation. "
            "Candidate code will run with your user privileges. "
            "Only use for trusted code.",
            UserWarning,
            stacklevel=2,
        )

        self._work_dir = (
            Path(work_dir) if work_dir else Path(tempfile.gettempdir()) / "omnievolve_trusted"
        )
        self._work_dir.mkdir(parents=True, exist_ok=True)
        self._artifact_store = artifact_store
        self._environment_version_id = f"trusted-{uuid.uuid4().hex[:8]}"

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

        在子进程中执行候选代码，应用基本资源限制。
        """
        # 准备工作目录
        exec_dir = self._work_dir / f"exec_{uuid.uuid4().hex[:8]}"
        exec_dir.mkdir(parents=True, exist_ok=True)

        start_time = time.time()
        return_codes = []
        all_stdout = []
        all_stderr = []
        timed_out = False

        try:
            # 写入候选代码
            if self._artifact_store:
                source_code = self._artifact_store.load(candidate.source_hash)
                code_file = exec_dir / "main.py"
                code_file.write_bytes(source_code)

            # 执行每个命令
            for cmd in plan.commands:
                try:
                    result = self._run_command(
                        cmd.argv,
                        cwd=str(exec_dir),
                        timeout=min(cmd.timeout_sec, policy.timeout_sec),
                        env=cmd.env,
                        policy=policy,
                    )
                    return_codes.append(result.returncode)
                    all_stdout.append(result.stdout)
                    all_stderr.append(result.stderr)

                    if result.returncode != 0:
                        break  # 命令失败，停止执行

                except subprocess.TimeoutExpired:
                    timed_out = True
                    return_codes.append(-1)
                    all_stdout.append("")
                    all_stderr.append("Command timed out")
                    break

            execution_time = (time.time() - start_time) * 1000

            # 收集输出产物
            output_artifacts = self._collect_outputs(exec_dir, plan.expected_outputs)

            return SandboxExecutionResult(
                return_codes=return_codes,
                stdout="\n".join(all_stdout),
                stderr="\n".join(all_stderr),
                output_artifacts=output_artifacts,
                execution_time_ms=execution_time,
                cpu_time_ms=execution_time,
                memory_peak_kb=0,
                timed_out=timed_out,
                policy_violation=None,
            )

        finally:
            # 清理工作目录
            import shutil

            try:
                shutil.rmtree(exec_dir, ignore_errors=True)
            except Exception:
                pass

    def _run_command(
        self,
        argv: list[str],
        cwd: str,
        timeout: float,
        env: dict[str, str],
        policy: SandboxPolicy,
    ) -> subprocess.CompletedProcess:
        """运行单个命令."""
        # 合并环境变量
        run_env = os.environ.copy()
        run_env.update(env)

        # 设置资源限制的 preexec_fn
        def set_limits():
            if hasattr(resource, "RLIMIT_AS"):
                # 内存限制
                mem_bytes = policy.mem_limit_mb * 1024 * 1024
                resource.setrlimit(resource.RLIMIT_AS, (mem_bytes, mem_bytes))

            if hasattr(resource, "RLIMIT_CPU"):
                # CPU 时间限制
                cpu_sec = int(policy.timeout_sec)
                resource.setrlimit(resource.RLIMIT_CPU, (cpu_sec, cpu_sec))

            if hasattr(resource, "RLIMIT_NPROC"):
                # 进程数限制
                resource.setrlimit(resource.RLIMIT_NPROC, (policy.pids_limit, policy.pids_limit))

        return subprocess.run(
            argv,
            cwd=cwd,
            env=run_env,
            capture_output=True,
            text=True,
            timeout=timeout,
            preexec_fn=set_limits if os.name != "nt" else None,
        )

    def _collect_outputs(self, exec_dir: Path, expected_outputs: list[str]) -> dict[str, str]:
        """收集预期输出产物."""
        outputs: dict[str, str] = {}

        if not expected_outputs or self._artifact_store is None:
            return outputs

        for output_name in expected_outputs:
            output_path = exec_dir / output_name
            if output_path.exists():
                content = output_path.read_bytes()
                artifact_hash = self._artifact_store.store(content, "report")
                outputs[output_name] = artifact_hash

        return outputs

    def healthcheck(self) -> dict:
        """健康检查."""
        return {
            "status": "healthy",
            "backend": "trusted_subprocess",
            "warning": "This backend does NOT provide security isolation",
            "platform": os.name,
            "rlimit_available": hasattr(resource, "RLIMIT_AS"),
        }
