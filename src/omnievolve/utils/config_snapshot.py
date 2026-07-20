"""配置快照、校验与秘密遮蔽.

S9-11: 实现配置快照、校验与秘密遮蔽

配置快照在实验创建时持久化（experiment.config_snapshot JSON 字段），
用于审计和复现。敏感值必须被遮蔽后才能输出或记录。
"""

from __future__ import annotations

import re
from typing import Any

# 敏感字段名模式（匹配 key 名，大小写不敏感）
SENSITIVE_KEY_PATTERNS = re.compile(
    r"(?i)(api[_-]?key|secret|token|password|passwd|credential|private[_-]?key|access[_-]?key)"
)

# 敏感环境变量名
SENSITIVE_ENV_PATTERNS = re.compile(r"(?i)(API_KEY|SECRET|TOKEN|PASSWORD|CREDENTIAL|PRIVATE_KEY)")


def mask_value(value: Any, visible_chars: int = 4) -> str:
    """遮蔽敏感值，仅保留前 visible_chars 个字符可见."""
    s = str(value)
    if len(s) <= visible_chars:
        return "***"
    return s[:visible_chars] + "***"


def mask_secrets(data: dict[str, Any]) -> dict[str, Any]:
    """递归遮蔽字典中的敏感字段.

    匹配 key 名中包含 api_key / secret / token / password 等模式的字段。
    """
    masked: dict[str, Any] = {}
    for key, value in data.items():
        if SENSITIVE_KEY_PATTERNS.search(key):
            masked[key] = mask_value(value) if value is not None else None
        elif isinstance(value, dict):
            masked[key] = mask_secrets(value)
        elif isinstance(value, list):
            masked[key] = [mask_secrets(v) if isinstance(v, dict) else v for v in value]
        else:
            masked[key] = value
    return masked


def mask_env_vars(env: dict[str, str]) -> dict[str, str]:
    """遮蔽敏感环境变量."""
    result: dict[str, str] = {}
    for key, value in env.items():
        if SENSITIVE_ENV_PATTERNS.search(key):
            result[key] = mask_value(value)
        else:
            result[key] = value
    return result


def validate_config_snapshot(snapshot: dict[str, Any]) -> tuple[bool, list[str]]:
    """校验配置快照完整性.

    Returns:
        (is_valid, errors)
    """
    errors: list[str] = []

    if "evolution" not in snapshot:
        errors.append("Missing [evolution] section")
    else:
        evo = snapshot["evolution"]
        if not isinstance(evo.get("max_generations"), int):
            errors.append("[evolution] max_generations must be an integer")
        if evo.get("population_size", 0) < 1:
            errors.append("[evolution] population_size must be >= 1")

    if "sandbox" not in snapshot:
        errors.append("Missing [sandbox] section")
    else:
        sb = snapshot["sandbox"]
        if sb.get("timeout_sec", 0) <= 0:
            errors.append("[sandbox] timeout_sec must be > 0")
        if sb.get("backend") not in ("docker", "trusted_subprocess", "hardened"):
            errors.append("[sandbox] backend must be docker/trusted_subprocess/hardened")

    return len(errors) == 0, errors


def create_audit_snapshot(
    settings_dict: dict[str, Any],
    *,
    evaluator_spec: str | None = None,
    config_path: str | None = None,
) -> dict[str, Any]:
    """创建审计安全（已遮蔽）的配置快照.

    Args:
        settings_dict: OmniEvolveSettings 的字典表示
        evaluator_spec: 评估器路径
        config_path: 配置文件路径

    Returns:
        可安全持久化/输出的遮蔽后快照
    """
    snapshot = {
        "config_path": config_path,
        "evaluator": evaluator_spec,
        "settings": mask_secrets(settings_dict),
    }
    return snapshot
