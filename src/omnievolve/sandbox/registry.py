"""沙箱后端注册与检测.

S2-14: 实现 Backend Registry 与 doctor 检测
- Docker 不可用时给出诊断，不静默降级到 trusted
"""

from __future__ import annotations

import logging
from typing import Any

from omnievolve.sandbox.base import SandboxBackend, SandboxSetupError

logger = logging.getLogger(__name__)


class BackendRegistry:
    """沙箱后端注册表.

    管理可用的执行后端，提供检测和诊断功能。
    """

    def __init__(self) -> None:
        self._backends: dict[str, type] = {}
        self._instances: dict[str, SandboxBackend] = {}

    def register(self, name: str, backend_class: type) -> None:
        """注册后端类."""
        self._backends[name] = backend_class

    def get_backend(
        self,
        name: str,
        **kwargs: Any,
    ) -> SandboxBackend:
        """获取或创建后端实例.

        Args:
            name: 后端名称 (docker / trusted_subprocess / hardened)
            **kwargs: 后端初始化参数

        Returns:
            后端实例

        Raises:
            SandboxSetupError: 后端不可用
        """
        # 检查缓存
        cache_key = f"{name}:{hash(frozenset(kwargs.items()))}"
        if cache_key in self._instances:
            return self._instances[cache_key]

        # 检查注册
        if name not in self._backends:
            available = ", ".join(self._backends.keys())
            raise SandboxSetupError(f"Unknown backend: {name}. Available: {available}")

        # 创建实例
        backend_class = self._backends[name]
        try:
            instance = backend_class(**kwargs)
        except Exception as e:
            raise SandboxSetupError(f"Failed to create backend '{name}': {e}")

        # 健康检查
        health = instance.healthcheck()
        if health.get("status") != "healthy":
            error = health.get("error", "Unknown error")
            raise SandboxSetupError(
                f"Backend '{name}' is not healthy: {error}\n"
                f"Run 'omnievolve doctor' for diagnostics."
            )

        self._instances[cache_key] = instance
        return instance

    def doctor(self) -> dict[str, Any]:
        """诊断所有后端.

        Returns:
            诊断结果字典
        """
        results = {}

        for name, backend_class in self._backends.items():
            try:
                # 尝试创建实例（不传参数）
                if name == "trusted_subprocess":
                    # trusted 需要显式参数
                    instance = backend_class(trusted=True)
                else:
                    instance = backend_class()

                health = instance.healthcheck()
                results[name] = {
                    "available": health.get("status") == "healthy",
                    "details": health,
                }
            except Exception as e:
                results[name] = {
                    "available": False,
                    "error": str(e),
                }

        return results

    def get_default_backend(self, **kwargs: Any) -> tuple[str, SandboxBackend]:
        """获取默认可用后端.

        优先级：docker > hardened > trusted_subprocess

        注意：不会静默降级到 trusted_subprocess，
        如果 Docker 不可用会抛出异常。

        Returns:
            (后端名称, 后端实例)
        """
        # 尝试 Docker
        try:
            backend = self.get_backend("docker", **kwargs)
            return "docker", backend
        except SandboxSetupError as e:
            docker_error = str(e)

        # Docker 不可用，不静默降级
        raise SandboxSetupError(
            f"Docker backend is not available: {docker_error}\n\n"
            "Options:\n"
            "1. Install and start Docker\n"
            "2. Use --trusted flag for TrustedSubprocessBackend (NOT SECURE)\n"
            "3. Configure a hardened backend\n\n"
            "Run 'omnievolve doctor' for detailed diagnostics."
        )


# 全局注册表
_registry = BackendRegistry()


def get_registry() -> BackendRegistry:
    """获取全局注册表."""
    return _registry


def register_default_backends() -> None:
    """注册默认后端."""
    from omnievolve.sandbox.docker_backend import DockerBackend
    from omnievolve.sandbox.subprocess_backend import TrustedSubprocessBackend

    _registry.register("docker", DockerBackend)
    _registry.register("trusted_subprocess", TrustedSubprocessBackend)


def create_backend(
    backend_type: str,
    *,
    trusted: bool = False,
    **kwargs: Any,
) -> SandboxBackend:
    """创建沙箱后端的便捷函数.

    Args:
        backend_type: 后端类型 (docker / trusted_subprocess)
        trusted: 是否启用 trusted 模式（仅用于 trusted_subprocess）
        **kwargs: 后端参数

    Returns:
        后端实例
    """
    register_default_backends()

    if backend_type == "trusted_subprocess":
        if not trusted:
            raise ValueError(
                "TrustedSubprocessBackend requires --trusted flag. "
                "This backend does NOT provide security isolation."
            )
        return _registry.get_backend("trusted_subprocess", trusted=True, **kwargs)

    return _registry.get_backend(backend_type, **kwargs)
