"""PromptVersion Repository.

S5-04: 实现 PromptVersion Repository
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from omnievolve.storage.db import Database
from omnievolve.storage.repositories.base import generate_id, now_iso


@dataclass
class PromptVersion:
    """Prompt 版本."""

    id: str
    agent_role: str  # director/coder/critic/meta
    version: int
    content_hash: str
    parent_id: str | None = None
    search_policy_id: str | None = None
    status: str = "challenger"  # challenger/champion/rejected/retired
    created_at: str | None = None


class PromptVersionRepository:
    """Prompt 版本 Repository."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def create(
        self,
        agent_role: str,
        content: str,
        *,
        search_policy_id: str | None = None,
        parent_id: str | None = None,
        artifact_store: Any | None = None,
    ) -> PromptVersion:
        """创建 Prompt 版本.

        Args:
            agent_role: Agent 角色
            content: Prompt 内容
            search_policy_id: 关联策略 ID
            parent_id: 父版本 ID
            artifact_store: ArtifactStore（存储 prompt 内容）
        """
        from omnievolve.utils.hashing import compute_sha256_str

        content_hash = compute_sha256_str(content)

        # 如果有 ArtifactStore，存储 prompt 内容，并用返回的 ref 作为 content_hash
        # （GitCodeStore 的 FK 注册使用 git blob SHA，而非 SHA-256）
        if artifact_store:
            stored_ref = artifact_store.store_text(content, "log", meta={"type": "prompt"})
            if stored_ref:
                content_hash = stored_ref

        # 获取下一个版本号
        row = self._db.fetchone(
            "SELECT MAX(version) as max_ver FROM prompt_version WHERE agent_role = ?",
            (agent_role,),
        )
        next_version = (row["max_ver"] or 0) + 1 if row else 1

        prompt = PromptVersion(
            id=generate_id(),
            agent_role=agent_role,
            version=next_version,
            content_hash=content_hash,
            parent_id=parent_id,
            search_policy_id=search_policy_id,
            status="challenger",
            created_at=now_iso(),
        )

        self._db.execute(
            """
            INSERT INTO prompt_version
                (id, agent_role, version, content_hash, parent_id,
                 search_policy_id, status)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                prompt.id,
                prompt.agent_role,
                prompt.version,
                prompt.content_hash,
                prompt.parent_id,
                prompt.search_policy_id,
                prompt.status,
            ),
        )

        return prompt

    def get(self, prompt_id: str) -> PromptVersion | None:
        """获取."""
        row = self._db.fetchone("SELECT * FROM prompt_version WHERE id = ?", (prompt_id,))
        if row is None:
            return None
        return self._row_to_prompt(row)

    def get_latest(self, agent_role: str, status: str = "champion") -> PromptVersion | None:
        """获取最新的指定状态版本."""
        row = self._db.fetchone(
            """
            SELECT * FROM prompt_version
            WHERE agent_role = ? AND status = ?
            ORDER BY version DESC
            LIMIT 1
            """,
            (agent_role, status),
        )
        if row is None:
            return None
        return self._row_to_prompt(row)

    def promote(self, prompt_id: str) -> bool:
        """晋升为 champion（同时将同角色的其他 champion 降级）."""
        with self._db.transaction() as conn:
            prompt = self.get(prompt_id)
            if prompt is None:
                return False

            # 将同角色的 champion 降级
            conn.execute(
                """
                UPDATE prompt_version
                SET status = 'retired'
                WHERE agent_role = ? AND status = 'champion'
                """,
                (prompt.agent_role,),
            )

            # 晋升当前版本
            cursor = conn.execute(
                "UPDATE prompt_version SET status = 'champion' WHERE id = ?",
                (prompt_id,),
            )
            return cursor.rowcount > 0

    def reject(self, prompt_id: str) -> bool:
        """拒绝."""
        cursor = self._db.execute(
            "UPDATE prompt_version SET status = 'rejected' WHERE id = ?",
            (prompt_id,),
        )
        return cursor.rowcount > 0

    def list_by_role(
        self,
        agent_role: str,
        *,
        status: str | None = None,
        limit: int = 50,
    ) -> list[PromptVersion]:
        """列出角色的 Prompt 版本."""
        if status:
            rows = self._db.fetchall(
                """
                SELECT * FROM prompt_version
                WHERE agent_role = ? AND status = ?
                ORDER BY version DESC LIMIT ?
                """,
                (agent_role, status, limit),
            )
        else:
            rows = self._db.fetchall(
                """
                SELECT * FROM prompt_version
                WHERE agent_role = ?
                ORDER BY version DESC LIMIT ?
                """,
                (agent_role, limit),
            )
        return [self._row_to_prompt(row) for row in rows]

    def _row_to_prompt(self, row: Any) -> PromptVersion:
        return PromptVersion(
            id=row["id"],
            agent_role=row["agent_role"],
            version=row["version"],
            content_hash=row["content_hash"],
            parent_id=row["parent_id"],
            search_policy_id=row["search_policy_id"],
            status=row["status"],
            created_at=row["created_at"],
        )
