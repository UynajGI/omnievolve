"""预算预设档位.

开箱即用的配置预设，覆盖 common use cases。
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

PRESETS_DIR = Path(__file__).parent.parent.parent.parent / "configs" / "presets"

BUDGET_PRESETS: dict[str, dict] = {
    "small": {
        "max_generations": 10,
        "population_size": 4,
        "island_count": 1,
        "token_budget": 200_000,
        "compute_budget_sec": 600,
        "description": "快速验证 — 10 代 × 4 候选，适合 CI/测试",
    },
    "medium": {
        "max_generations": 50,
        "population_size": 8,
        "island_count": 2,
        "token_budget": 2_000_000,
        "compute_budget_sec": 3600,
        "description": "标准运行 — 50 代 × 8 候选，适合日常优化",
    },
    "large": {
        "max_generations": 200,
        "population_size": 16,
        "island_count": 4,
        "token_budget": 10_000_000,
        "compute_budget_sec": 14400,
        "description": "深度搜索 — 200 代 × 16 候选，适合关键任务",
    },
}


def list_presets() -> list[str]:
    """列出可用预设."""
    return sorted(BUDGET_PRESETS.keys())


def get_preset_config(preset_name: str) -> dict:
    """获取预设配置字典.

    Raises:
        KeyError: 如果预设不存在
    """
    if preset_name not in BUDGET_PRESETS:
        raise KeyError(
            f"Unknown preset '{preset_name}'. Available: {list_presets()}"
        )
    return BUDGET_PRESETS[preset_name]


def apply_preset(settings_dict: dict, preset_name: str) -> dict:
    """将预设应用到设置字典.

    预设值作为基础，用户配置覆盖预设。
    """
    preset = get_preset_config(preset_name)
    result = dict(preset)
    result.pop("description", None)

    # 用户配置覆盖预设
    result.update(settings_dict)
    return result
