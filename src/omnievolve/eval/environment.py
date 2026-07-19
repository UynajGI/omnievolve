"""ExecutionEnvironmentVersion 管理.

S2-02: 定义 ExecutionEnvironmentVersion 规范
- 镜像、命令、资源限制、编译器、依赖锁均进入 digest
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from omnievolve.utils.hashing import compute_sha256_str


@dataclass(frozen=True)
class ExecutionEnvironmentVersion:
    """执行环境版本.

    记录执行候选代码的环境配置，用于结果复现和审计。
    """

    id: str
    backend: str  # docker / trusted_subprocess / hardened
    image_digest: str | None = None
    compiler_digest: str | None = None
    dependency_lock_hash: str | None = None
    cpu_profile: str | None = None
    resource_policy: dict[str, Any] = field(default_factory=dict)
    network_policy: str = "none"
    created_at: str | None = None

    def compute_digest(self) -> str:
        """计算环境配置的 digest.

        所有影响执行结果的配置都进入 digest。
        """
        digest_input = json.dumps(
            {
                "backend": self.backend,
                "image_digest": self.image_digest,
                "compiler_digest": self.compiler_digest,
                "dependency_lock_hash": self.dependency_lock_hash,
                "cpu_profile": self.cpu_profile,
                "resource_policy": self.resource_policy,
                "network_policy": self.network_policy,
            },
            sort_keys=True,
            ensure_ascii=False,
        )
        return compute_sha256_str(digest_input)

    def to_dict(self) -> dict[str, Any]:
        """转换为字典."""
        return {
            "id": self.id,
            "backend": self.backend,
            "image_digest": self.image_digest,
            "compiler_digest": self.compiler_digest,
            "dependency_lock_hash": self.dependency_lock_hash,
            "cpu_profile": self.cpu_profile,
            "resource_policy": json.dumps(self.resource_policy),
            "network_policy": self.network_policy,
        }

    @classmethod
    def from_row(cls, row: Any) -> ExecutionEnvironmentVersion:
        """从数据库 Row 创建."""
        return cls(
            id=row["id"],
            backend=row["backend"],
            image_digest=row["image_digest"],
            compiler_digest=row["compiler_digest"],
            dependency_lock_hash=row["dependency_lock_hash"],
            cpu_profile=row["cpu_profile"],
            resource_policy=json.loads(row["resource_policy"]) if row["resource_policy"] else {},
            network_policy=row["network_policy"],
            created_at=row["created_at"],
        )


def create_docker_environment(
    image: str,
    *,
    mem_limit_mb: int = 512,
    cpu_limit: float = 1.0,
    pids_limit: int = 64,
    network_mode: str = "none",
    dependency_lock_hash: str | None = None,
) -> ExecutionEnvironmentVersion:
    """创建 Docker 执行环境版本."""
    from omnievolve.storage.repositories.base import generate_id

    env = ExecutionEnvironmentVersion(
        id=generate_id(),
        backend="docker",
        image_digest=image,
        resource_policy={
            "mem_limit_mb": mem_limit_mb,
            "cpu_limit": cpu_limit,
            "pids_limit": pids_limit,
        },
        network_policy=network_mode,
        dependency_lock_hash=dependency_lock_hash,
    )
    return env


def create_trusted_subprocess_environment(
    *,
    mem_limit_mb: int = 512,
    cpu_limit: float = 1.0,
    timeout_sec: float = 30.0,
) -> ExecutionEnvironmentVersion:
    """创建 Trusted Subprocess 执行环境版本.

    注意：此后端不提供真正的安全隔离。
    """
    from omnievolve.storage.repositories.base import generate_id

    env = ExecutionEnvironmentVersion(
        id=generate_id(),
        backend="trusted_subprocess",
        resource_policy={
            "mem_limit_mb": mem_limit_mb,
            "cpu_limit": cpu_limit,
            "timeout_sec": timeout_sec,
        },
        network_policy="host",  # subprocess 无法限制网络
    )
    return env
