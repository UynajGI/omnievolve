"""Job Lease / Heartbeat / Recovery.

S4-05: 实现 Job Lease/Heartbeat/Expiry
S4-06: 实现幂等键与结果提交协议
S4-13: 实现 resume 与 orphan job recovery
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from omnievolve.storage.db import Database
from omnievolve.storage.repositories.base import generate_id, now_iso
from omnievolve.utils import safe_json_loads

logger = logging.getLogger(__name__)


@dataclass
class Job:
    """异步任务."""

    id: str
    experiment_id: str
    job_type: str
    payload: dict[str, Any]
    status: str = "queued"  # queued/running/completed/failed/cancelled
    attempt: int = 0
    max_attempts: int = 3
    lease_owner: str | None = None
    lease_expires_at: str | None = None
    heartbeat_at: str | None = None
    result_ref: str | None = None
    last_error: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class JobStore:
    """任务租约存储.

    支持 kill -9 恢复：
    - 租约过期任务可重新认领
    - 已完成任务不重复提交
    """

    def __init__(
        self,
        db: Database,
        *,
        lease_sec: int = 120,
        heartbeat_sec: int = 20,
    ) -> None:
        self._db = db
        self._lease_sec = lease_sec
        self._heartbeat_sec = heartbeat_sec
        self._worker_id = f"worker-{uuid.uuid4().hex[:8]}"

    @property
    def worker_id(self) -> str:
        return self._worker_id

    def create_job(
        self,
        experiment_id: str,
        job_type: str,
        payload: dict[str, Any],
        *,
        max_attempts: int = 3,
    ) -> Job:
        """创建任务."""
        job = Job(
            id=generate_id(),
            experiment_id=experiment_id,
            job_type=job_type,
            payload=payload,
            max_attempts=max_attempts,
            created_at=now_iso(),
            updated_at=now_iso(),
        )

        self._db.execute(
            """
            INSERT INTO job
                (id, experiment_id, job_type, payload, status, attempt, max_attempts,
                 created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job.id,
                job.experiment_id,
                job.job_type,
                json.dumps(job.payload),
                job.status,
                job.attempt,
                job.max_attempts,
                job.created_at,
                job.updated_at,
            ),
        )

        return job

    def claim_job(self, job_type: str | None = None) -> Job | None:
        """认领任务（获取租约）.

        原子操作：只有成功更新状态的 worker 获得任务。
        """
        lease_expires = self._compute_lease_expiry()

        # 查找可认领的任务：queued 或租约过期的 running
        if job_type:
            row = self._db.fetchone(
                """
                SELECT * FROM job
                WHERE job_type = ?
                  AND (status = 'queued' OR (status = 'running' AND lease_expires_at < ?))
                  AND attempt < max_attempts
                ORDER BY created_at
                LIMIT 1
                """,
                (job_type, now_iso()),
            )
        else:
            row = self._db.fetchone(
                """
                SELECT * FROM job
                WHERE (status = 'queued' OR (status = 'running' AND lease_expires_at < ?))
                  AND attempt < max_attempts
                ORDER BY created_at
                LIMIT 1
                """,
                (now_iso(),),
            )

        if row is None:
            return None

        return self._claim_by_id(row["id"], lease_expires)

    def claim_job_by_id(self, job_id: str) -> Job | None:
        """按 ID 直接认领指定任务.

        用于 create_job 后立即 claim 同一个 job，避免 claim_job() 认领到其他排队任务。
        """
        lease_expires = self._compute_lease_expiry()
        return self._claim_by_id(job_id, lease_expires)

    def _claim_by_id(self, job_id: str, lease_expires: str) -> Job | None:
        """内部: 原子认领指定 ID 的任务."""
        cursor = self._db.execute(
            """
            UPDATE job
            SET status = 'running',
                lease_owner = ?,
                lease_expires_at = ?,
                attempt = attempt + 1,
                heartbeat_at = ?,
                updated_at = ?
            WHERE id = ? AND (status = 'queued' OR (status = 'running' AND lease_expires_at < ?))
            """,
            (
                self._worker_id,
                lease_expires,
                now_iso(),
                now_iso(),
                job_id,
                now_iso(),
            ),
        )

        if cursor.rowcount == 0:
            return None

        return self.get_job(job_id)

    def heartbeat(self, job_id: str) -> bool:
        """心跳续租."""
        lease_expires = self._compute_lease_expiry()

        cursor = self._db.execute(
            """
            UPDATE job
            SET heartbeat_at = ?,
                lease_expires_at = ?,
                updated_at = ?
            WHERE id = ? AND lease_owner = ? AND status = 'running'
            """,
            (now_iso(), lease_expires, now_iso(), job_id, self._worker_id),
        )
        return cursor.rowcount > 0

    def complete_job(self, job_id: str, result_ref: str | None = None) -> bool:
        """完成任务."""
        cursor = self._db.execute(
            """
            UPDATE job
            SET status = 'completed',
                result_ref = ?,
                lease_owner = NULL,
                lease_expires_at = NULL,
                updated_at = ?
            WHERE id = ? AND lease_owner = ? AND status = 'running'
            """,
            (result_ref, now_iso(), job_id, self._worker_id),
        )
        return cursor.rowcount > 0

    def fail_job(self, job_id: str, error: str) -> bool:
        """标记任务失败."""
        cursor = self._db.execute(
            """
            UPDATE job
            SET status = CASE WHEN attempt >= max_attempts THEN 'failed' ELSE 'queued' END,
                last_error = ?,
                lease_owner = NULL,
                lease_expires_at = NULL,
                updated_at = ?
            WHERE id = ? AND lease_owner = ? AND status = 'running'
            """,
            (error, now_iso(), job_id, self._worker_id),
        )
        return cursor.rowcount > 0

    def get_job(self, job_id: str) -> Job | None:
        """获取任务."""
        row = self._db.fetchone("SELECT * FROM job WHERE id = ?", (job_id,))
        if row is None:
            return None
        return self._row_to_job(row)

    def list_jobs(
        self,
        experiment_id: str | None = None,
        status: str | None = None,
        job_type: str | None = None,
        limit: int = 100,
    ) -> list[Job]:
        """列出任务."""
        conditions = []
        params: list[Any] = []

        if experiment_id:
            conditions.append("experiment_id = ?")
            params.append(experiment_id)
        if status:
            conditions.append("status = ?")
            params.append(status)
        if job_type:
            conditions.append("job_type = ?")
            params.append(job_type)

        where = " AND ".join(conditions) if conditions else "1=1"
        params.append(limit)

        rows = self._db.fetchall(
            f"SELECT * FROM job WHERE {where} ORDER BY created_at DESC LIMIT ?",
            tuple(params),
        )
        return [self._row_to_job(row) for row in rows]

    def recover_orphan_jobs(self) -> int:
        """恢复孤儿任务（租约过期的 running 任务）.

        S4-13: 实现 resume 与 orphan job recovery

        Returns:
            恢复的任务数量
        """
        cursor = self._db.execute(
            """
            UPDATE job
            SET status = 'queued',
                lease_owner = NULL,
                lease_expires_at = NULL,
                updated_at = ?
            WHERE status = 'running' AND lease_expires_at < ?
            """,
            (now_iso(), now_iso()),
        )

        recovered = cursor.rowcount
        if recovered > 0:
            logger.info(f"Recovered {recovered} orphan jobs")
        return recovered

    def get_stats(self, experiment_id: str | None = None) -> dict[str, int]:
        """获取任务统计."""
        if experiment_id:
            rows = self._db.fetchall(
                """
                SELECT status, COUNT(*) as cnt
                FROM job
                WHERE experiment_id = ?
                GROUP BY status
                """,
                (experiment_id,),
            )
        else:
            rows = self._db.fetchall("SELECT status, COUNT(*) as cnt FROM job GROUP BY status")

        return {row["status"]: row["cnt"] for row in rows}

    def _compute_lease_expiry(self) -> str:
        """计算租约过期时间."""
        expiry = datetime.now(UTC) + timedelta(seconds=self._lease_sec)
        return expiry.isoformat()

    def _row_to_job(self, row: Any) -> Job:
        """Row 转 Job."""
        return Job(
            id=row["id"],
            experiment_id=row["experiment_id"],
            job_type=row["job_type"],
            payload=safe_json_loads(row["payload"], default={}),
            status=row["status"],
            attempt=row["attempt"],
            max_attempts=row["max_attempts"],
            lease_owner=row["lease_owner"],
            lease_expires_at=row["lease_expires_at"],
            heartbeat_at=row["heartbeat_at"],
            result_ref=row["result_ref"],
            last_error=row["last_error"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
