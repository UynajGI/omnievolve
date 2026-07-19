"""Evaluator Registry 与版本管理.

S3-03 ~ S3-04: 实现 Evaluator Registry 与版本 digest
- 评估器版本注册
- implementation_hash、dataset_hash、task_semantics_hash
- 不可变核心标志

S3-04: 实现任务语义不可变策略
"""

from __future__ import annotations

import inspect
import json
import logging
from dataclasses import dataclass
from typing import Any

from omnievolve.storage.db import Database
from omnievolve.storage.repositories.base import generate_id
from omnievolve.utils.hashing import compute_sha256_str

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EvaluatorVersionInfo:
    """评估器版本信息."""

    id: str
    name: str
    semantic_version: str
    implementation_hash: str
    dataset_hash: str | None
    task_semantics_hash: str
    score_schema: dict[str, Any]
    immutable_core: bool = True


class EvaluatorRegistry:
    """评估器注册表.

    管理评估器版本，确保评估语义不可变。
    """

    def __init__(self, db: Database) -> None:
        self._db = db

    def register(
        self,
        evaluator: Any,
        *,
        name: str | None = None,
        semantic_version: str = "1.0.0",
        dataset_hash: str | None = None,
        task_semantics_hash: str | None = None,
        score_schema: dict[str, Any] | None = None,
        immutable_core: bool = True,
    ) -> str:
        """注册评估器版本.

        Args:
            evaluator: TaskEvaluator 实现
            name: 评估器名称（默认从 version_id 提取）
            semantic_version: 语义版本
            dataset_hash: 数据集哈希
            task_semantics_hash: 任务语义哈希（默认自动计算）
            score_schema: 分数 schema
            immutable_core: 是否不可变核心

        Returns:
            评估器版本 ID
        """
        # 提取名称
        if name is None:
            version_id = getattr(evaluator, "version_id", None)
            if version_id:
                name = version_id.split("@")[0]
            else:
                name = type(evaluator).__name__

        # 计算 implementation hash
        implementation_hash = self._compute_implementation_hash(evaluator)

        # 计算 task semantics hash
        if task_semantics_hash is None:
            task_semantics_hash = self._compute_task_semantics_hash(evaluator, dataset_hash)

        # 默认 score schema
        if score_schema is None:
            score_schema = {"primary_score": "float", "passed": "bool"}

        version_id = generate_id()

        # 检查是否已存在相同版本
        existing = self._db.fetchone(
            """
            SELECT id FROM task_evaluator_version
            WHERE name = ? AND semantic_version = ? AND implementation_hash = ?
            """,
            (name, semantic_version, implementation_hash),
        )

        if existing:
            logger.info(f"Evaluator version already registered: {existing['id']}")
            return existing["id"]

        # 注册新版本
        self._db.execute(
            """
            INSERT INTO task_evaluator_version
                (id, name, semantic_version, implementation_hash, dataset_hash,
                 task_semantics_hash, score_schema, immutable_core)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                version_id,
                name,
                semantic_version,
                implementation_hash,
                dataset_hash,
                task_semantics_hash,
                json.dumps(score_schema),
                1 if immutable_core else 0,
            ),
        )

        logger.info(f"Registered evaluator: {name}@{semantic_version} ({version_id})")
        return version_id

    def get(self, version_id: str) -> EvaluatorVersionInfo | None:
        """获取评估器版本信息."""
        row = self._db.fetchone(
            "SELECT * FROM task_evaluator_version WHERE id = ?",
            (version_id,),
        )
        if row is None:
            return None

        return EvaluatorVersionInfo(
            id=row["id"],
            name=row["name"],
            semantic_version=row["semantic_version"],
            implementation_hash=row["implementation_hash"],
            dataset_hash=row["dataset_hash"],
            task_semantics_hash=row["task_semantics_hash"],
            score_schema=json.loads(row["score_schema"]),
            immutable_core=bool(row["immutable_core"]),
        )

    def get_by_name(
        self, name: str, semantic_version: str | None = None
    ) -> list[EvaluatorVersionInfo]:
        """根据名称获取评估器版本."""
        if semantic_version:
            rows = self._db.fetchall(
                """
                SELECT * FROM task_evaluator_version
                WHERE name = ? AND semantic_version = ?
                ORDER BY created_at DESC
                """,
                (name, semantic_version),
            )
        else:
            rows = self._db.fetchall(
                "SELECT * FROM task_evaluator_version WHERE name = ? ORDER BY created_at DESC",
                (name,),
            )

        return [
            EvaluatorVersionInfo(
                id=row["id"],
                name=row["name"],
                semantic_version=row["semantic_version"],
                implementation_hash=row["implementation_hash"],
                dataset_hash=row["dataset_hash"],
                task_semantics_hash=row["task_semantics_hash"],
                score_schema=json.loads(row["score_schema"]),
                immutable_core=bool(row["immutable_core"]),
            )
            for row in rows
        ]

    def verify_immutability(self, version_id: str, evaluator: Any) -> bool:
        """验证评估器实现是否被修改.

        Args:
            version_id: 已注册的版本 ID
            evaluator: 当前评估器实例

        Returns:
            True 如果实现未变，False 如果实现已变
        """
        info = self.get(version_id)
        if info is None:
            raise ValueError(f"Evaluator version not found: {version_id}")

        if not info.immutable_core:
            return True  # 非不可变核心，跳过验证

        current_hash = self._compute_implementation_hash(evaluator)
        return current_hash == info.implementation_hash

    def _compute_implementation_hash(self, evaluator: Any) -> str:
        """计算评估器实现的哈希.

        基于评估器的 build_plan 和 parse_result 方法的源代码。
        """
        try:
            # 获取关键方法的源代码
            source_parts = []

            for method_name in ["build_plan", "parse_result", "get_baseline"]:
                method = getattr(evaluator, method_name, None)
                if method:
                    try:
                        source = inspect.getsource(method)
                        source_parts.append(source)
                    except (OSError, TypeError):
                        # 无法获取源代码（如内置方法）
                        pass

            if source_parts:
                combined = "\n".join(source_parts)
                return compute_sha256_str(combined)

            # 回退：使用类名和 version_id
            fallback = f"{type(evaluator).__name__}:{getattr(evaluator, 'version_id', '')}"
            return compute_sha256_str(fallback)

        except Exception as e:
            logger.warning(f"Failed to compute implementation hash: {e}")
            return compute_sha256_str(str(type(evaluator)))

    def _compute_task_semantics_hash(self, evaluator: Any, dataset_hash: str | None) -> str:
        """计算任务语义哈希.

        任务语义包括：评估逻辑、数据集、评分公式。
        """
        semantics_parts = [
            self._compute_implementation_hash(evaluator),
            dataset_hash or "no_dataset",
            str(getattr(evaluator, "get_baseline", lambda: 0)()),
        ]
        return compute_sha256_str("|".join(semantics_parts))


class ImmutabilityViolationError(Exception):
    """不可变性违规错误."""

    pass


def check_evaluator_immutability(
    registry: EvaluatorRegistry,
    version_id: str,
    evaluator: Any,
) -> None:
    """检查评估器不可变性，违规时抛出异常.

    S3-04: 实现任务语义不可变策略
    """
    info = registry.get(version_id)
    if info is None:
        raise ValueError(f"Evaluator version not found: {version_id}")

    if not info.immutable_core:
        return

    if not registry.verify_immutability(version_id, evaluator):
        raise ImmutabilityViolationError(
            f"Evaluator implementation has changed for version {version_id}. "
            "Task semantics, correctness tests, and score formulas are immutable. "
            "Register a new version if intentional."
        )
