"""内容寻址 Artifact Store（SHA-256）.

S1-06: 实现 SHA-256 内容寻址与原子写入
- 临时文件 + fsync + rename
- 并发写同一内容只产生一个对象
- 去重、损坏检测与恢复

S1-07: 实现 Artifact Manifest 与 MIME/类型登记
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from omnievolve.storage.db import Database
from omnievolve.utils import safe_json_loads
from omnievolve.utils.hashing import (
    ArtifactManifest,
    artifact_path_from_hash,
    compute_sha256,
    compute_sha256_file,
    get_media_type,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ArtifactInfo:
    """Artifact 元数据."""

    hash: str
    artifact_type: str
    byte_size: int
    media_type: str | None
    relative_path: str
    base_artifact_hash: str | None = None
    meta: dict[str, Any] | None = None


class ArtifactStore:
    """内容寻址 Artifact Store.

    所有 Artifact 按 SHA-256 哈希存储在文件系统中：
    <root>/sha256/ab/cd/<full_hash>

    元数据存储在 SQLite artifact 表中。
    """

    def __init__(self, root_dir: str | Path, db: Database) -> None:
        self._root = Path(root_dir)
        self._db = db
        self._root.mkdir(parents=True, exist_ok=True)

    @property
    def root_dir(self) -> Path:
        return self._root

    def _artifact_path(self, artifact_hash: str) -> Path:
        """获取 artifact 的完整文件路径."""
        return self._root / artifact_path_from_hash(artifact_hash)

    def store(
        self,
        data: bytes,
        artifact_type: str,
        *,
        media_type: str | None = None,
        base_artifact_hash: str | None = None,
        meta: dict[str, Any] | None = None,
    ) -> str:
        """存储 Artifact 并返回哈希.

        原子写入：tmpfile + fsync + rename
        去重：同一内容只存储一次

        Args:
            data: 要存储的字节数据
            artifact_type: artifact 类型 (source/diff/manifest/log/report/binary)
            media_type: MIME 类型（可选，自动推断）
            base_artifact_hash: 基础 artifact 哈希（用于 diff）
            meta: 附加元数据

        Returns:
            SHA-256 哈希
        """
        artifact_hash = compute_sha256(data)
        relative_path = artifact_path_from_hash(artifact_hash)
        target_path = self._root / relative_path

        # 去重检查：文件已存在则跳过写入
        if not target_path.exists():
            self._atomic_write(target_path, data)

        # 推断 media_type
        if media_type is None:
            media_type = get_media_type(artifact_type)

        # 写入元数据（幂等）
        meta_json = json.dumps(meta) if meta else None
        with self._db.transaction() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO artifact
                    (hash, artifact_type, byte_size, media_type, relative_path,
                     base_artifact_hash, meta)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    artifact_hash,
                    artifact_type,
                    len(data),
                    media_type,
                    relative_path,
                    base_artifact_hash,
                    meta_json,
                ),
            )

        return artifact_hash

    def store_text(
        self,
        text: str,
        artifact_type: str,
        *,
        media_type: str | None = None,
        base_artifact_hash: str | None = None,
        meta: dict[str, Any] | None = None,
    ) -> str:
        """存储文本 Artifact."""
        return self.store(
            text.encode("utf-8"),
            artifact_type,
            media_type=media_type,
            base_artifact_hash=base_artifact_hash,
            meta=meta,
        )

    def store_manifest(self, manifest: ArtifactManifest) -> str:
        """存储 Manifest Artifact."""
        return self.store_text(
            manifest.to_json(),
            "manifest",
            media_type="application/json",
        )

    def load(self, artifact_hash: str) -> bytes:
        """加载 Artifact 内容.

        Raises:
            FileNotFoundError: artifact 不存在
            ValueError: artifact 损坏（哈希不匹配）
        """
        path = self._artifact_path(artifact_hash)
        if not path.exists():
            raise FileNotFoundError(f"Artifact not found: {artifact_hash}")

        data = path.read_bytes()

        # 完整性校验
        actual_hash = compute_sha256(data)
        if actual_hash != artifact_hash:
            raise ValueError(f"Artifact corrupted: expected {artifact_hash}, got {actual_hash}")

        return data

    def load_text(self, artifact_hash: str) -> str:
        """加载文本 Artifact."""
        return self.load(artifact_hash).decode("utf-8")

    def load_manifest(self, artifact_hash: str) -> ArtifactManifest:
        """加载 Manifest Artifact."""
        return ArtifactManifest.from_json(self.load_text(artifact_hash))

    def exists(self, artifact_hash: str) -> bool:
        """检查 Artifact 是否存在（文件和元数据）."""
        path = self._artifact_path(artifact_hash)
        if not path.exists():
            return False

        row = self._db.fetchone("SELECT 1 FROM artifact WHERE hash = ?", (artifact_hash,))
        return row is not None

    def get_info(self, artifact_hash: str) -> ArtifactInfo | None:
        """获取 Artifact 元数据."""
        row = self._db.fetchone("SELECT * FROM artifact WHERE hash = ?", (artifact_hash,))
        if row is None:
            return None

        return ArtifactInfo(
            hash=row["hash"],
            artifact_type=row["artifact_type"],
            byte_size=row["byte_size"],
            media_type=row["media_type"],
            relative_path=row["relative_path"],
            base_artifact_hash=row["base_artifact_hash"],
            meta=safe_json_loads(row["meta"], default=None),
        )

    def verify(self, artifact_hash: str) -> bool:
        """验证 Artifact 完整性.

        Returns:
            True 如果完整，False 如果损坏或不存在
        """
        path = self._artifact_path(artifact_hash)
        if not path.exists():
            return False

        try:
            actual_hash = compute_sha256_file(path)
            return actual_hash == artifact_hash
        except Exception as e:
            logger.debug("Artifact integrity check failed for %s: %s", artifact_hash[:12], e)
            return False

    def delete(self, artifact_hash: str) -> bool:
        """删除 Artifact（仅当无引用时）.

        P2: 引用计数检查 — 如果任何 candidate/evaluation_run/llm_call_ledger
        引用此 hash，则不删除。
        """
        # 引用检查
        if self._has_references(artifact_hash):
            logger.debug("Artifact %s still referenced, skipping delete", artifact_hash[:12])
            return False

        path = self._artifact_path(artifact_hash)
        if path.exists():
            path.unlink()

        with self._db.transaction() as conn:
            cursor = conn.execute("DELETE FROM artifact WHERE hash = ?", (artifact_hash,))
            return cursor.rowcount > 0

    def _has_references(self, artifact_hash: str) -> bool:
        """检查是否有数据库行引用此 artifact hash."""
        ref_columns = [
            ("candidate", "artifact_hash"),
            ("candidate", "diff_artifact_hash"),
            ("candidate", "manifest_hash"),
            ("evaluation_run", "stdout_hash"),
            ("evaluation_run", "stderr_hash"),
            ("evaluation_run", "result_hash"),
            ("llm_call_ledger", "response_hash"),
        ]
        for table, col in ref_columns:
            row = self._db.fetchone(
                f"SELECT 1 FROM {table} WHERE {col} = ? LIMIT 1",
                (artifact_hash,),
            )
            if row is not None:
                return True
        return False

    def garbage_collect(self, *, dry_run: bool = False) -> dict[str, int]:
        """垃圾回收：删除无引用的 artifact.

        扫描所有 artifact，删除没有被任何数据库行引用的。

        Returns:
            {"scanned": N, "deleted": M, "retained": K}
        """
        rows = self._db.fetchall("SELECT hash FROM artifact")
        scanned = len(rows)
        deleted = 0
        retained = 0

        for row in rows:
            artifact_hash = row["hash"]
            if self._has_references(artifact_hash):
                retained += 1
                continue
            if dry_run:
                deleted += 1
                continue
            # 删除文件和 DB 行
            path = self._artifact_path(artifact_hash)
            if path.exists():
                path.unlink(missing_ok=True)
            self._db.execute("DELETE FROM artifact WHERE hash = ?", (artifact_hash,))
            deleted += 1

        logger.info(
            "Artifact GC: scanned=%d, deleted=%d, retained=%d%s",
            scanned,
            deleted,
            retained,
            " (dry-run)" if dry_run else "",
        )
        return {"scanned": scanned, "deleted": deleted, "retained": retained}

    def _atomic_write(self, target_path: Path, data: bytes) -> None:
        """原子写入文件.

        使用 tmpfile + fsync + rename 确保写入原子性。
        """
        target_path.parent.mkdir(parents=True, exist_ok=True)

        # 创建临时文件
        fd, tmp_path = tempfile.mkstemp(
            dir=str(target_path.parent),
            prefix=".tmp_",
        )
        try:
            os.write(fd, data)
            os.fsync(fd)
            os.close(fd)

            # 原子发布且不覆盖已存在的 CAS 对象。并发写入相同内容时，
            # 只有一个硬链接创建成功，其余写入者安全地复用赢家的对象。
            try:
                os.link(tmp_path, target_path)
            except FileExistsError:
                pass
            finally:
                os.unlink(tmp_path)

            # fsync 目录确保元数据持久化（Windows 不支持目录 fsync，跳过）
            if os.name != "nt":
                dir_fd = os.open(str(target_path.parent), os.O_RDONLY)
                try:
                    os.fsync(dir_fd)
                finally:
                    os.close(dir_fd)

        except Exception:
            # 清理临时文件（fd 可能已在 L314 关闭）
            try:
                os.close(fd)
            except OSError:
                pass  # fd already closed
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            raise

    def list_artifacts(
        self,
        artifact_type: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ArtifactInfo]:
        """列出 Artifact."""
        if artifact_type:
            rows = self._db.fetchall(
                "SELECT * FROM artifact WHERE artifact_type = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (artifact_type, limit, offset),
            )
        else:
            rows = self._db.fetchall(
                "SELECT * FROM artifact ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            )

        return [
            ArtifactInfo(
                hash=row["hash"],
                artifact_type=row["artifact_type"],
                byte_size=row["byte_size"],
                media_type=row["media_type"],
                relative_path=row["relative_path"],
                base_artifact_hash=row["base_artifact_hash"],
                meta=safe_json_loads(row["meta"], default=None),
            )
            for row in rows
        ]

    def get_stats(self) -> dict[str, Any]:
        """获取存储统计信息."""
        total = self._db.fetchone("SELECT COUNT(*) as cnt FROM artifact")
        total_size = self._db.fetchone("SELECT COALESCE(SUM(byte_size), 0) as size FROM artifact")
        by_type = self._db.fetchall(
            "SELECT artifact_type, COUNT(*) as cnt FROM artifact GROUP BY artifact_type"
        )

        return {
            "total_count": total["cnt"] if total else 0,
            "total_size_bytes": total_size["size"] if total_size else 0,
            "by_type": {row["artifact_type"]: row["cnt"] for row in by_type},
        }
