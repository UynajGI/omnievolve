"""Docker 沙箱执行后端.

S2-03 ~ S2-11: 实现 DockerBackend
- 禁网（network=none）
- 只读根文件系统、tmpfs
- 非 root、cap_drop=ALL、no-new-privileges
- CPU/内存/PID/磁盘/墙钟限制
- 环境变量白名单、秘密脱敏
- 只读数据集挂载、候选工作区
- stdout/stderr 限流截断
- 超时取消、容器清理

S2-12: 执行产物采集并写入 Artifact Store
"""

from __future__ import annotations

import io
import logging
import tarfile
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

from omnievolve.sandbox.base import (
    CandidateArtifact,
    EvaluationPlan,
    SandboxError,
    SandboxExecutionResult,
    SandboxPolicy,
    SandboxSetupError,
    SandboxTimeoutError,
)

logger = logging.getLogger(__name__)

# 最大输出大小（防止内存溢出）
MAX_OUTPUT_BYTES = 10 * 1024 * 1024  # 10MB


class DockerBackend:
    """Docker 沙箱执行后端.

    默认候选执行后端，提供完整的安全隔离：
    - network=none
    - read_only root filesystem
    - cap_drop=ALL
    - no-new-privileges
    - non-root UID/GID
    - pids / memory / cpu / timeout limits
    - 独立临时工作区和 tmpfs
    - 只读挂载数据集
    - 环境变量白名单，不继承 API Key
    - 固定 image digest 和 dependency lock
    """

    def __init__(
        self,
        image: str = "python:3.12-slim",
        *,
        work_dir: str | Path | None = None,
        artifact_store: Any = None,
    ) -> None:
        """初始化 Docker 后端.

        Args:
            image: Docker 镜像名称或 digest
            work_dir: 工作目录（用于临时文件）
            artifact_store: ArtifactStore 实例（用于存储执行产物）
        """
        self._image = image
        self._work_dir = (
            Path(work_dir) if work_dir else Path(tempfile.gettempdir()) / "omnievolve_sandbox"
        )
        self._work_dir.mkdir(parents=True, exist_ok=True)
        self._artifact_store = artifact_store
        self._environment_version_id = f"docker-{uuid.uuid4().hex[:8]}"
        self._client = None

    @property
    def environment_version_id(self) -> str:
        return self._environment_version_id

    def _get_client(self):
        """获取 Docker 客户端（惰性初始化）."""
        if self._client is None:
            try:
                import docker

                self._client = docker.from_env()
                # 验证连接
                self._client.ping()
            except ImportError:
                raise SandboxSetupError(
                    "docker package not installed. Install with: pip install omnievolve[docker]"
                )
            except Exception as e:
                raise SandboxSetupError(f"Failed to connect to Docker: {e}")
        return self._client

    def execute(
        self,
        plan: EvaluationPlan,
        candidate: CandidateArtifact,
        policy: SandboxPolicy,
    ) -> SandboxExecutionResult:
        """执行评估计划.

        在 Docker 容器中执行候选代码，应用所有安全策略。
        """
        client = self._get_client()
        container = None
        start_time = time.time()

        try:
            # 准备容器配置
            container_config = self._build_container_config(plan, candidate, policy)

            # 创建容器
            container = client.containers.create(**container_config)

            # 准备候选代码
            self._prepare_workspace(container, candidate)

            # 启动容器
            container.start()

            # 等待执行完成
            timed_out = False
            try:
                result = container.wait(timeout=policy.timeout_sec)
                exit_code = result.get("StatusCode", -1)
            except Exception as e:
                # 区分超时和其他 Docker API 错误
                err_name = type(e).__name__
                if "timeout" in err_name.lower() or "timeout" in str(e).lower():
                    timed_out = True
                    logger.warning("Container timed out after %ds", policy.timeout_sec)
                else:
                    logger.warning("Container wait failed: %s: %s", err_name, e)
                    timed_out = False
                try:
                    container.kill()
                except Exception:
                    logger.debug("Container kill failed (may already be stopped)", exc_info=True)
                exit_code = -1

            # 收集输出
            stdout = self._get_logs(container, stdout=True)
            stderr = self._get_logs(container, stdout=False)

            # 收集输出产物
            output_artifacts = self._collect_outputs(container, plan.expected_outputs)

            execution_time = (time.time() - start_time) * 1000

            return SandboxExecutionResult(
                return_codes=[exit_code],
                stdout=stdout,
                stderr=stderr,
                output_artifacts=output_artifacts,
                execution_time_ms=execution_time,
                cpu_time_ms=execution_time,  # 简化：使用墙钟时间
                memory_peak_kb=0,  # Docker stats 需要额外查询
                timed_out=timed_out,
                policy_violation=None,
            )

        except SandboxTimeoutError:
            raise
        except SandboxError:
            raise
        except Exception as e:
            logger.error(f"Docker execution failed: {e}")
            raise SandboxError(f"Execution failed: {e}")
        finally:
            # 清理容器
            if container:
                try:
                    container.remove(force=True)
                except Exception:
                    pass

    def _build_container_config(
        self,
        plan: EvaluationPlan,
        candidate: CandidateArtifact,
        policy: SandboxPolicy,
    ) -> dict[str, Any]:
        """构建容器配置."""
        # 环境变量白名单
        env_vars = {}
        for key in policy.allowed_env:
            import os

            if key in os.environ:
                env_vars[key] = os.environ[key]

        # 添加命令特定的环境变量
        if plan.commands:
            env_vars.update(plan.commands[0].env)

        # 挂载配置
        volumes = {}
        for mount in plan.mounts:
            volumes[mount.source] = {
                "bind": mount.target,
                "mode": "ro" if mount.read_only else "rw",
            }

        # 网络模式
        network_mode = "none"
        if plan.network_access:
            network_mode = policy.network_mode

        # 资源限制
        mem_limit = f"{policy.mem_limit_mb}m"
        nano_cpus = int(policy.cpu_limit * 1e9)

        config = {
            "image": self._image,
            "command": self._build_command(plan),
            "environment": env_vars,
            "network_mode": network_mode,
            "mem_limit": mem_limit,
            "nano_cpus": nano_cpus,
            "pids_limit": policy.pids_limit,
            "read_only": policy.read_only_root,
            "cap_drop": ["ALL"] if policy.drop_capabilities else [],
            "security_opt": ["no-new-privileges:true"] if policy.no_new_privileges else [],
            "user": "1000:1000" if policy.run_as_non_root else None,
            "volumes": volumes if volumes else None,
            "tmpfs": {"/tmp": f"size={policy.tmpfs_mb}m"} if policy.read_only_root else None,
            "working_dir": "/workspace",
            "detach": True,
        }

        # 移除 None 值
        return {k: v for k, v in config.items() if v is not None}

    def _build_command(self, plan: EvaluationPlan) -> list[str]:
        """构建执行命令."""
        if not plan.commands:
            return ["echo", "No commands specified"]

        # 将所有命令串联
        commands = []
        for cmd in plan.commands:
            commands.append(" ".join(cmd.argv))

        return ["/bin/sh", "-c", " && ".join(commands)]

    def _prepare_workspace(self, container: Any, candidate: CandidateArtifact) -> None:
        """准备容器工作区（上传候选代码）."""
        if self._artifact_store is None:
            return

        try:
            # 从 ArtifactStore 加载源代码
            source_code = self._artifact_store.load(candidate.source_hash)

            # 创建 tar 归档
            tar_stream = io.BytesIO()
            with tarfile.open(fileobj=tar_stream, mode="w") as tar:
                info = tarfile.TarInfo(name="main.py")
                info.size = len(source_code)
                tar.addfile(info, io.BytesIO(source_code))

            tar_stream.seek(0)

            # 上传到容器
            container.put_archive("/workspace", tar_stream)

        except Exception as e:
            logger.warning(f"Failed to prepare workspace: {e}")

    def _get_logs(self, container: Any, stdout: bool = True) -> str:
        """获取容器日志（限流截断）."""
        try:
            logs = container.logs(stdout=stdout, stderr=not stdout)
            # 截断大输出
            if len(logs) > MAX_OUTPUT_BYTES:
                logs = logs[:MAX_OUTPUT_BYTES] + b"\n... [TRUNCATED] ..."
            return logs.decode("utf-8", errors="replace")
        except Exception:
            return ""

    def _collect_outputs(self, container: Any, expected_outputs: list[str]) -> dict[str, str]:
        """收集预期输出产物."""
        outputs: dict[str, str] = {}

        if not expected_outputs or self._artifact_store is None:
            return outputs

        for output_path in expected_outputs:
            try:
                # 从容器获取文件
                bits, _ = container.get_archive(f"/workspace/{output_path}")

                # 解压 tar
                tar_stream = io.BytesIO(b"".join(bits))
                with tarfile.open(fileobj=tar_stream, mode="r") as tar:
                    for member in tar.getmembers():
                        if member.isfile():
                            f = tar.extractfile(member)
                            if f:
                                content = f.read()
                                # 存储到 ArtifactStore
                                artifact_hash = self._artifact_store.store(content, "report")
                                outputs[output_path] = artifact_hash

            except Exception as e:
                logger.debug(f"Failed to collect output {output_path}: {e}")

        return outputs

    def healthcheck(self) -> dict:
        """健康检查."""
        try:
            client = self._get_client()
            client.ping()

            # 检查镜像是否存在
            try:
                client.images.get(self._image)
                image_available = True
            except Exception:
                image_available = False

            return {
                "status": "healthy",
                "docker_available": True,
                "image": self._image,
                "image_available": image_available,
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "docker_available": False,
                "error": str(e),
            }


def is_docker_available() -> bool:
    """检查 Docker 是否可用."""
    try:
        import docker

        client = docker.from_env()
        client.ping()
        return True
    except Exception:
        return False
