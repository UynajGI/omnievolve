"""评估基础设施适配器（L1 允许，必须版本化 + Replay/Canary）.

S3 / ADR #10 / 设计 5.1.1:
    L2：默认永久禁止自动修改 — Task semantics / correctness tests / hidden data /
        metric definition / score aggregation / pass-fail 语义阈值
    L1：允许提出 Challenger，但必须版本化并 Replay/Canary — Timeout schedule /
        Progressive evaluation stages / Benchmark repetition / Resource allocation /
        Build cache / Compilation flags（不得改变任务语义）
    L0：可自动调整并记录 — 日志格式 / tracing / 非语义性结果采集 /
        临时目录和缓存回收

InfraAdapter 只能做 L1 以下的环境适配；任何 L2 变更直接拒绝。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from omnievolve.eval.environment import ExecutionEnvironmentVersion
from omnievolve.storage.db import Database
from omnievolve.storage.repositories.base import generate_id

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class InfraAdaptation:
    """单条基础设施适配提议.

    L1 适配必须：创建新 ExecutionEnvironmentVersion → 重跑 baseline →
    重跑 elite archive 固定样本 → 检查排名稳定性 → 通过门槛后晋升。
    """

    field_name: str  # timeout_schedule / progressive_stages / repetition / resource / cache / flags
    old_value: Any
    new_value: Any
    risk_level: str = "L1"  # L0 / L1
    rationale: str = ""


# L1 允许修改的字段白名单（不改变任务语义）
L1_ALLOWED_FIELDS: frozenset[str] = frozenset(
    {
        "timeout_schedule",
        "progressive_stages",
        "benchmark_repetition",
        "resource_allocation",
        "build_cache",
        "compilation_flags",
    }
)

# L0 允许自动调整的字段
L0_ALLOWED_FIELDS: frozenset[str] = frozenset(
    {
        "log_format",
        "tracing_format",
        "temp_dir",
        "cache_eviction",
        "result_collection",
    }
)


class InfraAdapter:
    """评估基础设施适配器.

    管理非语义性评估环境的版本化变更，确保：
    1. 每次变更创建新的 ExecutionEnvironmentVersion
    2. 重跑 baseline 并检查分数和排名稳定性
    3. 通过门槛后才晋升新版本
    4. 任何 L2（语义性）变更直接拒绝
    """

    def __init__(
        self,
        db: Database,
        *,
        min_rank_correlation: float = 0.95,
        max_baseline_drift: float = 0.02,
    ) -> None:
        self._db = db
        self._min_rank_correlation = min_rank_correlation
        self._max_baseline_drift = max_baseline_drift

    def classify(self, field_name: str) -> str:
        """分类字段的风险等级."""
        if field_name in L0_ALLOWED_FIELDS:
            return "L0"
        if field_name in L1_ALLOWED_FIELDS:
            return "L1"
        # 未知字段默认 L2（禁止）
        return "L2"

    def can_adapt(self, field_name: str) -> tuple[bool, str]:
        """检查字段是否可以被适配."""
        risk = self.classify(field_name)
        if risk == "L2":
            return False, f"{field_name} is L2 (semantic) — forbidden by default"
        return True, f"{field_name} is {risk} — allowed with versioning"

    def propose(
        self,
        current_env: ExecutionEnvironmentVersion,
        adaptation: InfraAdaptation,
    ) -> ExecutionEnvironmentVersion | None:
        """提议一个基础设施适配，创建新的环境版本（不晋升）.

        Returns:
            新的 ExecutionEnvironmentVersion，或 None（L2 拒绝）
        """
        can_adapt, reason = self.can_adapt(adaptation.field_name)
        if not can_adapt:
            logger.warning("Infra adaptation rejected: %s", reason)
            return None

        # 构建新环境版本
        new_policy = dict(current_env.resource_policy)
        new_policy[adaptation.field_name] = {
            "old": adaptation.old_value,
            "new": adaptation.new_value,
            "rationale": adaptation.rationale,
        }

        new_env = ExecutionEnvironmentVersion(
            id=generate_id(),
            backend=current_env.backend,
            image_digest=current_env.image_digest,
            compiler_digest=current_env.compiler_digest,
            dependency_lock_hash=current_env.dependency_lock_hash,
            cpu_profile=current_env.cpu_profile,
            resource_policy=new_policy,
            network_policy=current_env.network_policy,
        )

        # 持久化到 DB
        import json

        self._db.execute(
            """
            INSERT INTO execution_environment_version
                (id, backend, image_digest, compiler_digest,
                 dependency_lock_hash, cpu_profile, resource_policy, network_policy)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                new_env.id,
                new_env.backend,
                new_env.image_digest,
                new_env.compiler_digest,
                new_env.dependency_lock_hash,
                new_env.cpu_profile,
                json.dumps(new_env.resource_policy),
                new_env.network_policy,
            ),
        )

        logger.info(
            "Proposed infra adaptation: %s (%s → %s) as env %s",
            adaptation.field_name,
            adaptation.old_value,
            adaptation.new_value,
            new_env.id,
        )
        return new_env

    def validate_promotion(
        self,
        old_scores: list[float],
        new_scores: list[float],
        old_ranks: list[int],
        new_ranks: list[int],
    ) -> tuple[bool, str]:
        """验证新环境版本是否可以晋升.

        检查：
        1. Baseline 分数漂移不超过 max_baseline_drift
        2. Elite archive 排名相关性不低于 min_rank_correlation

        Args:
            old_scores: 旧环境下 baseline 的分数
            new_scores: 新环境下 baseline 的分数
            old_ranks: 旧环境下 elite archive 的排名
            new_ranks: 新环境下 elite archive 的排名

        Returns:
            (can_promote, reason)
        """
        if not old_scores or not new_scores:
            return False, "Insufficient data for comparison"

        # 1. Baseline 漂移
        import statistics

        old_mean = statistics.mean(old_scores)
        new_mean = statistics.mean(new_scores)
        drift = abs(new_mean - old_mean) / max(abs(old_mean), 0.001)

        if drift > self._max_baseline_drift:
            return False, f"Baseline drift {drift:.4f} exceeds {self._max_baseline_drift}"

        # 2. 排名相关性（Spearman 简化）
        rank_corr = self._spearman_correlation(old_ranks, new_ranks)
        if rank_corr < self._min_rank_correlation:
            return False, (f"Rank correlation {rank_corr:.4f} below {self._min_rank_correlation}")

        return True, f"Promotion validated (drift={drift:.4f}, rank_corr={rank_corr:.4f})"

    @staticmethod
    def _spearman_correlation(a: list[int], b: list[int]) -> float:
        """简化 Spearman 等级相关（假设输入已是排名）."""
        n = len(a)
        if n < 2:
            return 1.0
        d_squared = sum((a[i] - b[i]) ** 2 for i in range(n))
        return 1 - (6 * d_squared) / (n * (n * n - 1))
