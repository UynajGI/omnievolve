"""结构化日志 / provenance.

统一的结构化日志工具，支持 provenance 追踪。
支持标准 logging 和 structlog 两种后端。
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any


class StructuredFormatter(logging.Formatter):
    """结构化日志格式化器."""

    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "line": record.lineno,
        }

        if hasattr(record, "experiment_id"):
            log_data["experiment_id"] = record.experiment_id
        if hasattr(record, "candidate_id"):
            log_data["candidate_id"] = record.candidate_id
        if hasattr(record, "agent_role"):
            log_data["agent_role"] = record.agent_role
        if hasattr(record, "extra_data"):
            log_data["extra"] = record.extra_data

        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_data, ensure_ascii=False)


def setup_structlog(
    level: str = "INFO",
    *,
    json_format: bool = True,
) -> None:
    """使用 structlog 配置结构化日志.

    Gap P2: 结构化日志 — structlog 生产级配置。
    若 structlog 未安装，回退到标准 StructuredFormatter。

    Args:
        level: 日志级别
        json_format: True 输出 JSON，False 输出彩色 console
    """
    try:
        import structlog

        processors: list[Any] = [
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.set_exc_info,
        ]

        if json_format:
            processors.append(structlog.processors.JSONRenderer())
        else:
            processors.append(structlog.dev.ConsoleRenderer(colors=True))

        structlog.configure(
            processors=processors,
            wrapper_class=structlog.stdlib.BoundLogger,
            context_class=dict,
            logger_factory=structlog.stdlib.LoggerFactory(),
            cache_logger_on_first_use=True,
        )

        logging.basicConfig(
            format="%(message)s",
            stream=sys.stderr,
            level=getattr(logging, level.upper()),
        )

    except ImportError:
        setup_logging(level=level, structured=json_format)


def setup_logging(
    level: str = "INFO",
    *,
    structured: bool = True,
    log_file: str | None = None,
) -> None:
    """配置日志.

    Args:
        level: 日志级别
        structured: 是否使用结构化 JSON 格式
        log_file: 日志文件路径（None 表示只输出到 stderr）
    """
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper()))

    # 清除现有 handler
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    if structured:
        formatter: logging.Formatter = StructuredFormatter()
    else:
        formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    # stderr handler
    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setFormatter(formatter)
    root_logger.addHandler(stderr_handler)

    # 文件 handler
    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)


class ProvenanceLogger:
    """Provenance 日志器 - 记录来源追踪信息."""

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self._logger = logger or logging.getLogger("omnievolve.provenance")

    def log_candidate_creation(
        self,
        candidate_id: str,
        experiment_id: str,
        parents: list[str],
        thought_id: str | None,
        artifact_hash: str,
        search_policy_id: str,
    ) -> None:
        """记录候选创建."""
        self._logger.info(
            "Candidate created",
            extra={
                "candidate_id": candidate_id,
                "experiment_id": experiment_id,
                "extra_data": {
                    "parents": parents,
                    "thought_id": thought_id,
                    "artifact_hash": artifact_hash,
                    "search_policy_id": search_policy_id,
                },
            },
        )

    def log_evaluation(
        self,
        candidate_id: str,
        experiment_id: str,
        evaluator_version_id: str,
        environment_version_id: str,
        score: float,
        passed: bool,
    ) -> None:
        """记录评估."""
        self._logger.info(
            "Evaluation completed",
            extra={
                "candidate_id": candidate_id,
                "experiment_id": experiment_id,
                "extra_data": {
                    "evaluator_version_id": evaluator_version_id,
                    "environment_version_id": environment_version_id,
                    "score": score,
                    "passed": passed,
                },
            },
        )

    def log_llm_call(
        self,
        experiment_id: str,
        agent_role: str,
        model: str,
        prompt_version_id: str | None,
        input_tokens: int,
        output_tokens: int,
    ) -> None:
        """记录 LLM 调用."""
        self._logger.info(
            "LLM call",
            extra={
                "experiment_id": experiment_id,
                "agent_role": agent_role,
                "extra_data": {
                    "model": model,
                    "prompt_version_id": prompt_version_id,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                },
            },
        )

    def log_policy_change(
        self,
        experiment_id: str,
        old_policy_id: str,
        new_policy_id: str,
        risk_level: str,
        evidence: dict[str, Any],
    ) -> None:
        """记录策略变更."""
        self._logger.info(
            "Policy change",
            extra={
                "experiment_id": experiment_id,
                "extra_data": {
                    "old_policy_id": old_policy_id,
                    "new_policy_id": new_policy_id,
                    "risk_level": risk_level,
                    "evidence": evidence,
                },
            },
        )
