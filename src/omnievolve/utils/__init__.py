"""OmniEvolve 工具模块."""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


def safe_json_loads(data: str | None, default: Any = None) -> Any:
    """安全 JSON 解析 — 数据库字段损坏时返回 default 而非崩溃.

    Args:
        data: JSON 字符串或 None
        default: 解析失败时的返回值
    """
    if not data:
        return default
    try:
        return json.loads(data)
    except (json.JSONDecodeError, TypeError) as e:
        logger.warning("JSON parse failed, returning default: %s", e)
        return default
