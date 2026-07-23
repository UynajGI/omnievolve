"""非语义性评估基础设施适配 (L1 级别变更).

设计文档 §5.1.1: 管理 ExecutionEnvironmentVersion 变更，
如 sandbox 参数调整、超时配置、资源配额等非语义性变更。

L1 变更不需要 Replay/Canary，但需要审计记录和可回滚。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class EnvChangeProposal:
    """环境变更提案."""

    change_type: str  # timeout / memory / concurrency / sandbox_params
    current_value: Any
    proposed_value: Any
    rationale: str = ""
    risk_level: str = "L1"  # L1 = 非语义性，无需 Replay


class InfraAdapter:
    """非语义性评估基础设施适配器.

    负责提出、应用和回滚执行环境的非语义性参数变更。
    这些变更不影响评估语义（分数计算、正确性判定），
    只影响执行效率或资源使用。

    示例变更:
    - sandbox 超时从 30s 调整为 60s（候选代码变复杂）
    - 内存限制从 512MB 调整为 1GB
    - 并发评估数从 4 调整为 8
    """

    def __init__(self, db: Any = None) -> None:
        self._db = db
        self._change_history: list[dict] = []

    def propose_env_change(
        self,
        current_env: dict,
        health: dict,
    ) -> EnvChangeProposal | None:
        """根据系统健康度提出环境变更建议.

        Args:
            current_env: 当前执行环境参数
            health: 系统健康度指标

        Returns:
            变更提案，或 None（无需变更）
        """
        # 规则: 如果超时失败率 > 20%，建议增加超时
        timeout_failures = health.get("timeout_failure_rate", 0.0)
        current_timeout = current_env.get("sandbox_timeout", 30)

        if timeout_failures > 0.2 and current_timeout < 120:
            proposed = min(current_timeout * 2, 120)
            return EnvChangeProposal(
                change_type="timeout",
                current_value=current_timeout,
                proposed_value=proposed,
                rationale=f"Timeout failure rate {timeout_failures:.1%} > 20%",
            )

        # 规则: 如果 OOM 率 > 10%，建议增加内存
        oom_rate = health.get("oom_failure_rate", 0.0)
        current_mem = current_env.get("sandbox_mem_limit_mb", 512)

        if oom_rate > 0.1 and current_mem < 2048:
            proposed = min(current_mem * 2, 2048)
            return EnvChangeProposal(
                change_type="memory",
                current_value=current_mem,
                proposed_value=proposed,
                rationale=f"OOM failure rate {oom_rate:.1%} > 10%",
            )

        return None

    def apply_env_change(
        self,
        env_version_id: str,
        change: EnvChangeProposal,
    ) -> bool:
        """应用环境变更（L1 级别，无需 Replay）.

        Args:
            env_version_id: 当前环境版本 ID
            change: 变更提案

        Returns:
            是否成功应用
        """
        # 记录变更历史（审计）
        self._change_history.append({
            "env_version_id": env_version_id,
            "change_type": change.change_type,
            "old_value": change.current_value,
            "new_value": change.proposed_value,
            "rationale": change.rationale,
            "risk_level": change.risk_level,
        })

        logger.info(
            "InfraAdapter: applied %s change (%s → %s) on env %s",
            change.change_type,
            change.current_value,
            change.proposed_value,
            env_version_id,
        )
        return True

    def rollback_env(self, env_version_id: str) -> bool:
        """回滚最近的环境变更.

        Args:
            env_version_id: 环境版本 ID

        Returns:
            是否成功回滚
        """
        # 找到该环境的最近变更
        for i in range(len(self._change_history) - 1, -1, -1):
            entry = self._change_history[i]
            if entry["env_version_id"] == env_version_id:
                logger.info(
                    "InfraAdapter: rolling back %s change (%s → %s) on env %s",
                    entry["change_type"],
                    entry["new_value"],
                    entry["old_value"],
                    env_version_id,
                )
                self._change_history.pop(i)
                return True

        logger.warning("InfraAdapter: no change history for env %s", env_version_id)
        return False

    def get_change_history(self, env_version_id: str | None = None) -> list[dict]:
        """获取变更历史."""
        if env_version_id:
            return [h for h in self._change_history if h["env_version_id"] == env_version_id]
        return list(self._change_history)
