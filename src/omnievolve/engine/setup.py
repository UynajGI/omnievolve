"""Engine Setup — 提取自 EvolutionEngine.

T1 重构第五步：将引擎初始化时的 setup 逻辑（版本行、champion policy、
embedding profile、L2 验证）从引擎中分离。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from omnievolve.meta.policy_archive import PolicyArchive
    from omnievolve.meta.policy_genome import SearchPolicyGenome
    from omnievolve.storage.db import Database
    from omnievolve.storage.repositories.experiment_repo import ExperimentRepository

logger = logging.getLogger(__name__)


class EngineSetup:
    """引擎启动时的一次性 setup 操作."""

    def __init__(
        self,
        db: Database,
        experiment_repo: ExperimentRepository,
        policy_archive: PolicyArchive,
    ) -> None:
        self._db = db
        self._experiment_repo = experiment_repo
        self._policy_archive = policy_archive

    def ensure_version_rows(
        self,
        evaluator_version_id: str,
        environment_version_id: str,
        task_evaluator: Any,
    ) -> tuple[str | None, str | None]:
        """确保 evaluator/environment version 行存在以满足 FK 约束.

        Returns:
            (evaluator_version_id, code_profile_id)
        """
        if evaluator_version_id:
            name = (
                evaluator_version_id.split("@")[0]
                if "@" in evaluator_version_id
                else evaluator_version_id
            )
            self._db.execute(
                "INSERT OR IGNORE INTO task_evaluator_version"
                "(id, name, semantic_version, implementation_hash, "
                " task_semantics_hash, score_schema, immutable_core) "
                "VALUES (?, ?, '1.0.0', ?, ?, '{}', 1)",
                (evaluator_version_id, name, evaluator_version_id, evaluator_version_id),
            )
            self._verify_evaluator_immutability(evaluator_version_id, task_evaluator)

        if environment_version_id:
            self._db.execute(
                "INSERT OR IGNORE INTO execution_environment_version"
                "(id, backend, resource_policy, network_policy) "
                "VALUES (?, 'engine', '{}', 'none')",
                (environment_version_id,),
            )

        code_profile_id = self._ensure_embedding_profile("code")
        return evaluator_version_id or None, code_profile_id

    def verify_evaluator_immutability(
        self,
        evaluator_version_id: str,
        task_evaluator: Any,
    ) -> None:
        """L2 红线入口."""
        self._verify_evaluator_immutability(evaluator_version_id, task_evaluator)

    def _verify_evaluator_immutability(
        self,
        evaluator_version_id: str,
        task_evaluator: Any,
    ) -> None:
        """L2 红线：验证评估器实现未被篡改."""
        from omnievolve.eval.evaluator_registry import (
            EvaluatorRegistry,
            ImmutabilityViolationError,
        )

        row = self._db.fetchone(
            "SELECT implementation_hash, immutable_core FROM task_evaluator_version WHERE id = ?",
            (evaluator_version_id,),
        )
        if row is None or not row["immutable_core"]:
            return

        stored_hash = row["implementation_hash"]
        if stored_hash == evaluator_version_id:
            return  # 占位行，跳过

        registry = EvaluatorRegistry(self._db)
        if not registry.verify_immutability(evaluator_version_id, task_evaluator):
            raise ImmutabilityViolationError(
                f"Evaluator implementation has changed for version "
                f"{evaluator_version_id}. Task semantics are immutable (L2). "
                "Register a new version if intentional."
            )

    def ensure_champion_policy(
        self,
        experiment_id: str,
        search_policy: SearchPolicyGenome,
    ) -> tuple[str, SearchPolicyGenome]:
        """确保实验存在一个初始 Champion Policy.

        Returns:
            (champion_policy_id, search_policy)
        """
        champ = self._policy_archive.get_champion(experiment_id)
        if champ is None:
            policy = self._policy_archive.create_policy(
                search_policy,
                experiment_id=experiment_id or None,
                risk_level="L0",
            )
            self._policy_archive.promote_to_champion(policy.id)
            champion_policy_id = policy.id
        else:
            champion_policy_id = champ.id
            search_policy = champ.genome

        if experiment_id:
            try:
                self._experiment_repo.set_champion_policy(experiment_id, champion_policy_id)
            except Exception:
                logger.debug("Could not set champion_policy_id on experiment")

        return champion_policy_id, search_policy

    @staticmethod
    def ensure_embedding_profile(db: Database, purpose: str) -> str:
        """确保 embedding_profile 行存在."""
        profile_id = f"profile-{purpose}-default"
        db.execute(
            "INSERT OR IGNORE INTO embedding_profile"
            "(id, purpose, provider, model, revision, dimension, normalization,"
            " input_type, chunking_policy, collection_path) "
            "VALUES (?, ?, 'fake', 'fake-embed', 'default', 64, 'l2', 'document',"
            " 'whole', ?)",
            (profile_id, purpose, f"collections/{purpose}"),
        )
        return profile_id

    def _ensure_embedding_profile(self, purpose: str) -> str:
        """实例方法包装（兼容引擎内部调用）."""
        return self.ensure_embedding_profile(self._db, purpose)

    @staticmethod
    def classify_task(
        task_name: str,
        task_desc: str,
        llm: object | None = None,
        categories: list[str] | None = None,
    ) -> str:
        """Phase 8: 任务分类 — 为 coldstart 策略提供分类信息.

        精简版 MLEvolve classify_tasks.py，单次 LLM 调用。
        失败时返回 "other"。
        """
        categories = categories or [
            "optimization",
            "sorting",
            "matrix",
            "geometry",
            "algorithm",
            "other",
        ]

        if llm is None:
            return "other"

        try:
            from omnievolve.agents.llm_gateway import LLMGateway

            if not isinstance(llm, LLMGateway):
                return "other"

            prompt = f"""Classify this task into one of these categories:
{", ".join(categories)}

Task: {task_name}
Description: {task_desc[:500]}

Respond with JSON: {{"category": "<category>"}}"""

            response = llm.chat(
                messages=[{"role": "user", "content": prompt}],
                model="light",
                role="critic",
            )

            from omnievolve.utils.response import extract_jsons

            jsons = extract_jsons(response)
            if jsons:
                cat = jsons[0].get("category", "other")
                if cat in categories:
                    return cat
        except Exception:
            logger.debug("Task classification failed", exc_info=True)

        return "other"
