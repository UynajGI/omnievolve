"""Monty 安全 Python 执行后端.

使用 Pydantic Monty（Rust 实现的安全 Python 解释器）执行候选代码。
微秒级启动，进程级崩溃隔离，默认断网，虚拟文件系统。

S2-20: MontyBackend — 第四种沙箱后端
"""

from __future__ import annotations

import io
import logging
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

from omnievolve.sandbox.base import (
    CandidateArtifact,
    EvaluationPlan,
    SandboxExecutionResult,
    SandboxPolicy,
    SandboxSetupError,
)

logger = logging.getLogger(__name__)

MAX_OUTPUT_BYTES = 1_000_000  # 1 MB


class MontyBackend:
    """Monty 安全执行后端.

    特性：
    - Rust 实现，微秒级启动（vs Docker 秒级）
    - 进程级崩溃隔离（segfault 不传播）
    - 默认断网、无宿主文件系统访问
    - 资源硬限制：内存、时间、递归深度

    限制：
    - 仅支持纯 Python 代码（不能 import C 扩展如 numpy/jax）
    - 需要 pip install omnievolve[monty]
    - pydantic-monty API: Monty(code).run(limits={...}, print_callback=...)
    """

    def __init__(
        self,
        *,
        work_dir: str | Path | None = None,
        artifact_store: Any = None,
    ) -> None:
        """初始化 Monty 后端.

        Args:
            work_dir: 工作目录（Monty 不使用宿主 FS）
            artifact_store: ArtifactStore 实例
        """
        self._work_dir = Path(work_dir) if work_dir else Path(tempfile.gettempdir()) / "omnievolve_monty"
        self._artifact_store = artifact_store
        self._environment_version_id = f"monty-{uuid.uuid4().hex[:8]}"

    @property
    def environment_version_id(self) -> str:
        return self._environment_version_id

    def _check_installed(self) -> None:
        """检查 pydantic-monty 是否已安装."""
        try:
            import pydantic_monty  # noqa: F401
        except ImportError:
            raise SandboxSetupError(
                "pydantic-monty not installed. Install with: pip install omnievolve[monty]"
            )

    def execute(
        self,
        plan: EvaluationPlan,
        candidate: CandidateArtifact,
        policy: SandboxPolicy,
    ) -> SandboxExecutionResult:
        """执行评估计划.

        在 Monty 解释器中执行候选代码，应用资源限制。
        """
        self._check_installed()
        from pydantic_monty import Monty, MontyRuntimeError, ResourceLimits

        start_time = time.time()

        # 加载候选代码
        source_code = ""
        if self._artifact_store is not None:
            try:
                source_code = self._artifact_store.load(candidate.source_hash).decode(
                    "utf-8", errors="replace"
                )
            except Exception:
                logger.warning("Failed to load source from artifact store", exc_info=True)

        if not source_code:
            return SandboxExecutionResult(
                return_codes=[-1],
                stdout="",
                stderr="Source code not found in ArtifactStore",
                output_artifacts={},
                execution_time_ms=0,
                cpu_time_ms=0,
                memory_peak_kb=0,
                timed_out=False,
                policy_violation=None,
            )

        # 构建 ResourceLimits
        limits = ResourceLimits()
        if policy.timeout_sec > 0:
            limits["max_duration_secs"] = policy.timeout_sec
        if policy.mem_limit_mb > 0:
            limits["max_memory"] = policy.mem_limit_mb * 1024 * 1024

        stdout_buf = io.StringIO()
        stderr_buf = io.StringIO()

        def _print_callback(stream: str, text: str) -> None:
            if stream == "stdout":
                stdout_buf.write(text)
            else:
                stderr_buf.write(text)

        return_codes: list[int] = []
        timed_out = False
        policy_violation: str | None = None

        try:
            runner = Monty(source_code)
            runner.run(limits=limits, print_callback=_print_callback)
            return_codes = [0]

        except MontyRuntimeError as e:
            error_msg = str(e)
            if "Timeout" in error_msg or "time limit" in error_msg.lower():
                timed_out = True
                stderr_buf.write(f"\nTimeout: {error_msg}")
            elif "Memory" in error_msg or "memory limit" in error_msg.lower():
                policy_violation = f"memory_limit: {error_msg}"
                stderr_buf.write(f"\nMemory limit exceeded: {error_msg}")
            else:
                stderr_buf.write(f"\nRuntime error: {error_msg}")
            return_codes = [1]

        except Exception as e:
            error_type = type(e).__name__
            error_msg = str(e)
            if "Crashed" in error_type:
                stderr_buf.write(f"\nWorker crashed: {error_msg}")
            else:
                stderr_buf.write(f"\nExecution error ({error_type}): {error_msg}")
            return_codes = [1]

        execution_time_ms = (time.time() - start_time) * 1000

        stdout = stdout_buf.getvalue()
        stderr = stderr_buf.getvalue()

        # 截断大输出
        if len(stdout) > MAX_OUTPUT_BYTES:
            stdout = stdout[:MAX_OUTPUT_BYTES] + "\n... [TRUNCATED] ..."
        if len(stderr) > MAX_OUTPUT_BYTES:
            stderr = stderr[:MAX_OUTPUT_BYTES] + "\n... [TRUNCATED] ..."

        return SandboxExecutionResult(
            return_codes=return_codes,
            stdout=stdout,
            stderr=stderr,
            output_artifacts={},
            execution_time_ms=execution_time_ms,
            cpu_time_ms=execution_time_ms,
            memory_peak_kb=0,
            timed_out=timed_out,
            policy_violation=policy_violation,
        )

    def healthcheck(self) -> dict:
        """健康检查."""
        try:
            self._check_installed()
        except SandboxSetupError as e:
            return {"status": "unhealthy", "error": str(e)}

        try:
            from importlib.metadata import version

            from pydantic_monty import Monty

            runner = Monty("1 + 1")
            runner.run()
            return {
                "status": "healthy",
                "monty_available": True,
                "version": version("pydantic-monty"),
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "monty_available": False,
                "error": str(e),
            }


def is_monty_available() -> bool:
    """检查 Monty 是否可用."""
    try:
        from pydantic_monty import Monty

        runner = Monty("pass")
        runner.run()
        return True
    except Exception:
        return False
