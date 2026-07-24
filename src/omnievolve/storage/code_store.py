"""CodeStore 协议 — 代码存储后端抽象接口.

设计文档 §2: 代码存储可插拔后端 (CAS / Git)
ArtifactStore (SHA-256 CAS) 和 GitCodeStore (Git commit) 共同实现此接口。

Phase 0: Protocol + Factory
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from omnievolve.config import StorageSettings
    from omnievolve.storage.db import Database


@dataclass(frozen=True)
class WorktreeHandle:
    """物化工作区句柄.

    Attributes:
        path: 工作目录绝对路径
        backend_id: 后端标识 ("cas" | "git")
        needs_cleanup: 是否需要显式清理
    """

    path: Path
    backend_id: str
    needs_cleanup: bool


@runtime_checkable
class CodeStore(Protocol):
    """代码存储后端协议 — 引擎通过此接口操作候选代码.

    两个实现:
    - CASCodeStore: 包装现有 ArtifactStore (SHA-256 CAS)
    - GitCodeStore: Git commit 存储 (commit SHA + ancestry)
    """

    @property
    def backend_name(self) -> str:
        """后端名称 ("cas" | "git")."""
        ...

    def store_snapshot(
        self,
        code: str,
        *,
        parents: list[str] | None = None,
        message: str = "",
        meta: dict[str, Any] | None = None,
    ) -> str:
        """存储代码快照 → 返回 ref (CAS: SHA-256 / Git: commit SHA).

        Args:
            code: 候选代码全文
            parents: 父代 ref 列表 (Git 后端用于建立 ancestry)
            message: commit message (Git 后端使用)
            meta: 额外元数据
        """
        ...

    def load_snapshot(self, ref: str) -> str:
        """加载代码快照文本."""
        ...

    def exists(self, ref: str) -> bool:
        """检查 ref 是否存在."""
        ...

    def materialize(self, ref: str) -> WorktreeHandle:
        """物化工作区 (Git: worktree / CAS: tmpdir + write).

        用于沙箱评估 — 在隔离环境中 checkout 候选代码。
        """
        ...

    def release(self, handle: WorktreeHandle) -> None:
        """释放物化的工作区."""
        ...

    def diff(self, parent_ref: str, child_ref: str) -> str:
        """返回两个快照间的 unified diff."""
        ...

    def get_parents(self, ref: str) -> list[str]:
        """获取快照的父代 ref 列表."""
        ...

    def merge(self, parent_refs: list[str]) -> str | None:
        """多父代合并 (crossover)。冲突返回 None."""
        ...

    def checkpoint(self, name: str, ref: str) -> None:
        """创建命名检查点."""
        ...

    def list_checkpoints(self) -> list[tuple[str, str]]:
        """列出检查点 [(name, ref), ...]."""
        ...


def create_code_store(settings: StorageSettings, db: Database) -> CodeStore:
    """根据配置创建代码存储后端.

    Args:
        settings: 存储配置 (code_backend, git_repo_path, ...)
        db: 数据库实例 (CAS 后端需要)

    Returns:
        CodeStore 实例 (CASCodeStore 或 GitCodeStore)
    """
    if settings.code_backend == "git":
        from omnievolve.storage.git_code_store import GitCodeStore

        store = GitCodeStore(settings.git_repo_path, settings.git_worktree_dir)
        store.set_database(db)  # 注入 DB 用于 FK 兼容
        return store
    else:
        from omnievolve.storage.artifact_store import ArtifactStore
        from omnievolve.storage.cas_code_store import CASCodeStore

        return CASCodeStore(
            ArtifactStore(settings.artifact_dir, db),
            Path(settings.artifact_dir),
        )
