"""Policy Archive - Champion/Challenger 管理.

S9-02: 实现 SearchPolicyVersion Repository
S9-03: 实现 Policy Archive Champion/Challenger
S9-07: 实现策略应用与原子回滚
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from omnievolve.meta.policy_genome import SearchPolicyGenome
from omnievolve.storage.db import Database
from omnievolve.storage.repositories.base import generate_id, now_iso

logger = logging.getLogger(__name__)


@dataclass
class PolicyVersion:
    """策略版本."""

    id: str
    version: int
    genome: SearchPolicyGenome
    risk_level: str = "L0"  # L0/L1/L2
    status: str = "challenger"  # draft/challenger/champion/rejected/retired
    experiment_id: str | None = None
    parent_policy_id: str | None = None
    created_at: str | None = None


class PolicyArchive:
    """策略档案 - 管理 Champion/Challenger 生命周期.

    S9-03: 实现 Policy Archive Champion/Challenger
    S9-07: 实现策略应用与原子回滚
    """

    def __init__(self, db: Database) -> None:
        self._db = db

    def create_policy(
        self,
        genome: SearchPolicyGenome,
        *,
        experiment_id: str | None = None,
        parent_policy_id: str | None = None,
        risk_level: str = "L0",
    ) -> PolicyVersion:
        """创建策略版本."""
        # 获取版本号
        row = self._db.fetchone(
            "SELECT MAX(version) as max_ver FROM search_policy_version WHERE experiment_id IS ?",
            (experiment_id,),
        )
        next_version = (row["max_ver"] or 0) + 1 if row else 1

        policy = PolicyVersion(
            id=generate_id(),
            version=next_version,
            genome=genome,
            risk_level=risk_level,
            status="draft",
            experiment_id=experiment_id,
            parent_policy_id=parent_policy_id,
            created_at=now_iso(),
        )

        self._db.execute(
            """
            INSERT INTO search_policy_version
                (id, experiment_id, parent_policy_id, version, genome,
                 risk_level, status)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                policy.id,
                policy.experiment_id,
                policy.parent_policy_id,
                policy.version,
                json.dumps(genome.to_dict()),
                policy.risk_level,
                policy.status,
            ),
        )

        return policy

    def get(self, policy_id: str) -> PolicyVersion | None:
        """获取策略."""
        row = self._db.fetchone(
            "SELECT * FROM search_policy_version WHERE id = ?",
            (policy_id,),
        )
        if row is None:
            return None
        return self._row_to_policy(row)

    def get_champion(self, experiment_id: str | None = None) -> PolicyVersion | None:
        """获取当前 Champion."""
        if experiment_id:
            row = self._db.fetchone(
                """
                SELECT * FROM search_policy_version
                WHERE experiment_id = ? AND status = 'champion'
                ORDER BY version DESC LIMIT 1
                """,
                (experiment_id,),
            )
        else:
            row = self._db.fetchone(
                """
                SELECT * FROM search_policy_version
                WHERE status = 'champion'
                ORDER BY version DESC LIMIT 1
                """
            )

        if row is None:
            return None
        return self._row_to_policy(row)

    def list_challengers(self, experiment_id: str) -> list[PolicyVersion]:
        """列出 Challenger."""
        rows = self._db.fetchall(
            """
            SELECT * FROM search_policy_version
            WHERE experiment_id = ? AND status = 'challenger'
            ORDER BY version
            """,
            (experiment_id,),
        )
        return [self._row_to_policy(row) for row in rows]

    def promote_to_champion(self, policy_id: str) -> bool:
        """晋升为 Champion.

        S9-07: 将旧 champion 降级，晋升新 champion。
        """
        policy = self.get(policy_id)
        if policy is None:
            return False

        with self._db.transaction() as conn:
            # 将同实验的旧 champion 降级
            if policy.experiment_id:
                conn.execute(
                    """
                    UPDATE search_policy_version
                    SET status = 'retired'
                    WHERE experiment_id = ? AND status = 'champion'
                    """,
                    (policy.experiment_id,),
                )
            else:
                conn.execute(
                    """
                    UPDATE search_policy_version
                    SET status = 'retired'
                    WHERE status = 'champion'
                    """
                )

            # 晋升新 champion
            cursor = conn.execute(
                "UPDATE search_policy_version SET status = 'champion' WHERE id = ?",
                (policy_id,),
            )

            if cursor.rowcount > 0:
                logger.info(f"Promoted policy {policy_id} to champion")
                return True
            return False

    def reject(self, policy_id: str, reason: str = "") -> bool:
        """拒绝策略."""
        cursor = self._db.execute(
            """
            UPDATE search_policy_version
            SET status = 'rejected'
            WHERE id = ? AND status = 'challenger'
            """,
            (policy_id,),
        )
        if cursor.rowcount > 0:
            logger.info(f"Rejected policy {policy_id}: {reason}")
            return True
        return False

    def rollback(self, experiment_id: str) -> PolicyVersion | None:
        """回滚到上一个 Champion.

        S9-07: 实现策略应用与原子回滚
        """
        # 获取最近的 retired 策略
        row = self._db.fetchone(
            """
            SELECT * FROM search_policy_version
            WHERE experiment_id = ? AND status = 'retired'
            ORDER BY version DESC LIMIT 1
            """,
            (experiment_id,),
        )

        if row is None:
            return None

        old_policy = self._row_to_policy(row)

        # 将当前 champion 降级
        self._db.execute(
            """
            UPDATE search_policy_version
            SET status = 'rejected'
            WHERE experiment_id = ? AND status = 'champion'
            """,
            (experiment_id,),
        )

        # 恢复旧策略
        self._db.execute(
            "UPDATE search_policy_version SET status = 'champion' WHERE id = ?",
            (old_policy.id,),
        )

        logger.info(f"Rolled back to policy {old_policy.id}")
        return old_policy

    def export_policy(self, policy_id: str) -> dict[str, Any]:
        """导出策略（完整快照）."""
        policy = self.get(policy_id)
        if policy is None:
            return {}

        return {
            "id": policy.id,
            "version": policy.version,
            "genome": policy.genome.to_dict(),
            "risk_level": policy.risk_level,
            "status": policy.status,
            "experiment_id": policy.experiment_id,
            "parent_policy_id": policy.parent_policy_id,
            "created_at": policy.created_at,
        }

    def list_all(self, experiment_id: str | None = None) -> list[PolicyVersion]:
        """列出所有策略."""
        if experiment_id:
            rows = self._db.fetchall(
                """
                SELECT * FROM search_policy_version
                WHERE experiment_id = ?
                ORDER BY version
                """,
                (experiment_id,),
            )
        else:
            rows = self._db.fetchall("SELECT * FROM search_policy_version ORDER BY version")
        return [self._row_to_policy(row) for row in rows]

    def _row_to_policy(self, row: Any) -> PolicyVersion:
        genome_data = json.loads(row["genome"])
        return PolicyVersion(
            id=row["id"],
            version=row["version"],
            genome=SearchPolicyGenome.from_dict(genome_data),
            risk_level=row["risk_level"],
            status=row["status"],
            experiment_id=row["experiment_id"],
            parent_policy_id=row["parent_policy_id"],
            created_at=row["created_at"],
        )

    def import_policy(
        self,
        snapshot: dict[str, Any],
        *,
        experiment_id: str | None = None,
    ) -> PolicyVersion:
        """导入策略快照（Champion 完整导出/导入，S9-12）.

        从 export_policy() 产生的快照重建一个策略版本。
        基因组内容必须通过 SearchPolicyGenome.from_dict 验证。

        Args:
            snapshot: export_policy 产生的字典
            experiment_id: 目标实验 ID（None 时使用快照中的值）

        Returns:
            新创建的 PolicyVersion
        """
        genome = SearchPolicyGenome.from_dict(snapshot["genome"])

        target_exp = experiment_id or snapshot.get("experiment_id")

        policy = self.create_policy(
            genome,
            experiment_id=target_exp,
            parent_policy_id=snapshot.get("parent_policy_id"),
            risk_level=snapshot.get("risk_level", "L0"),
        )

        logger.info(
            "Imported policy %s from snapshot (source version=%s)",
            policy.id,
            snapshot.get("version"),
        )
        return policy
