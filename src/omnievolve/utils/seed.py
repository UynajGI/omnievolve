"""全局种子管理器.

参考 MLEvolve utils/seed.py: 统一随机种子管理，确保实验可复现。
为 Python random、NumPy、可选的 torch 提供组件级确定性种子派生。
"""

from __future__ import annotations

import hashlib
import logging
import os
import random
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_SEED = 42
_GLOBAL_SEED: int | None = None
_COMPONENT_SEEDS: dict[str, int] = {}


def set_global_seed(seed: int | None = None) -> int:
    """设置全局随机种子.

    设置 Python random 和 NumPy（若可用）的随机状态。
    返回使用的种子值。

    Args:
        seed: 种子值，若为 None 则使用环境变量 OMNI_SEED 或默认值 42

    Returns:
        实际使用的种子值
    """
    global _GLOBAL_SEED, _COMPONENT_SEEDS

    if seed is None:
        seed_str = os.environ.get("OMNI_SEED", str(_DEFAULT_SEED))
        try:
            seed = int(seed_str)
        except ValueError:
            seed = _DEFAULT_SEED
            logger.warning("Invalid OMNI_SEED=%r, using default %d", seed_str, seed)

    _GLOBAL_SEED = seed
    _COMPONENT_SEEDS.clear()

    random.seed(seed)

    try:
        import numpy as np

        np.random.seed(seed)
    except ImportError:
        pass

    logger.info("Global random seed set to %d", seed)
    return seed


def get_global_seed() -> int:
    """获取当前全局种子."""
    global _GLOBAL_SEED
    if _GLOBAL_SEED is None:
        return _DEFAULT_SEED
    return _GLOBAL_SEED


def derive_component_seed(component: str, base_seed: int | None = None) -> int:
    """为指定组件派生确定性种子.

    使用 MD5(component.encode() + base_seed.to_bytes()) 派生，
    确保同一 (component, base_seed) 组合始终产生相同种子。
    参考 OpenEvolve: MD5 哈希派生组件种子。

    Args:
        component: 组件标识符 (如 "mcts", "crossover", "llm_sampler")
        base_seed: 基础种子，默认为全局种子

    Returns:
        派生种子 (0..2^31-1)
    """
    global _COMPONENT_SEEDS, _GLOBAL_SEED

    if base_seed is None:
        base_seed = _GLOBAL_SEED if _GLOBAL_SEED is not None else _DEFAULT_SEED

    key = f"{base_seed}:{component}"
    if key in _COMPONENT_SEEDS:
        return _COMPONENT_SEEDS[key]

    digest = hashlib.md5(  # noqa: S324 - 非安全用途，仅确定性种子派生
        component.encode() + base_seed.to_bytes(8, "big")
    ).digest()
    derived = int.from_bytes(digest[:4], "big") % (2**31 - 1)
    _COMPONENT_SEEDS[key] = derived
    return derived


def seed_context(seed: int) -> dict[str, Any]:
    """创建可序列化的种子上下文.

    用于记录到实验配置快照中。
    """
    return {
        "global_seed": get_global_seed(),
        "requested_seed": seed,
        "component_seeds": dict(_COMPONENT_SEEDS),
        "random_state": random.getstate(),
    }


def reset_seeds() -> None:
    """重置所有种子状态（主要用于测试）."""
    global _GLOBAL_SEED, _COMPONENT_SEEDS
    _GLOBAL_SEED = None
    _COMPONENT_SEEDS.clear()
