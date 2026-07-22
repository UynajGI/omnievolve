"""定价目录自动刷新.

从 ShinkaEvolve pricing/catalog.py 精简移植。
从 models.dev API 获取最新模型定价，带缓存和 fallback。
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

logger = logging.getLogger(__name__)

MODELS_DEV_URL = "https://models.dev/api.json"
CACHE_DIR = Path.home() / ".omnievolve" / "cache"
CACHE_FILE = CACHE_DIR / "pricing_catalog.json"
CACHE_TTL_SEC = 86400  # 24 hours


class PricingMode(str, Enum):
    """定价获取模式."""

    AUTO = "auto"  # 尝试在线获取，失败用 fallback
    OFFLINE = "offline"  # 只用 fallback
    REQUIRED = "required"  # 必须在线获取，失败抛异常


# 内置 fallback 定价（per 1M tokens）
BUNDLED_PRICING: dict[str, dict[str, float]] = {
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4-turbo": {"input": 10.00, "output": 30.00},
    "o1": {"input": 15.00, "output": 60.00},
    "o1-mini": {"input": 3.00, "output": 12.00},
    "claude-3-5-sonnet": {"input": 3.00, "output": 15.00},
    "claude-3-opus": {"input": 15.00, "output": 75.00},
    "claude-3-haiku": {"input": 0.25, "output": 1.25},
    "gemini-1.5-pro": {"input": 1.25, "output": 5.00},
    "gemini-1.5-flash": {"input": 0.075, "output": 0.30},
    "deepseek-chat": {"input": 0.14, "output": 0.28},
    "deepseek-coder": {"input": 0.14, "output": 0.28},
}


@dataclass(frozen=True)
class ModelPrice:
    """单个模型的定价."""

    input_per_1m: float
    output_per_1m: float


class PricingCatalog:
    """模型定价目录 — 在线获取 + 缓存 + fallback."""

    def __init__(
        self,
        mode: PricingMode = PricingMode.AUTO,
        cache_file: Path | None = None,
    ) -> None:
        self._mode = mode
        self._cache_file = cache_file or CACHE_FILE
        self._prices: dict[str, ModelPrice] = {}
        self._loaded = False

    def _load_bundled(self) -> None:
        """加载内置 fallback 定价."""
        for model, pricing in BUNDLED_PRICING.items():
            self._prices[model.lower()] = ModelPrice(
                input_per_1m=pricing["input"],
                output_per_1m=pricing["output"],
            )

    def _load_cache(self) -> bool:
        """从本地缓存加载."""
        if not self._cache_file.exists():
            return False
        try:
            data = json.loads(self._cache_file.read_text())
            age = time.time() - data.get("timestamp", 0)
            if age > CACHE_TTL_SEC:
                return False
            for model, pricing in data.get("prices", {}).items():
                self._prices[model.lower()] = ModelPrice(
                    input_per_1m=pricing["input"],
                    output_per_1m=pricing["output"],
                )
            return True
        except Exception:
            return False

    def _fetch_online(self) -> bool:
        """从 models.dev 获取最新定价."""
        if self._mode == PricingMode.OFFLINE:
            return False
        try:
            import httpx

            resp = httpx.get(MODELS_DEV_URL, timeout=10.0)
            resp.raise_for_status()
            data = resp.json()

            for model_id, info in data.items():
                pricing = info.get("pricing", {})
                input_p = pricing.get("prompt", 0)
                output_p = pricing.get("completion", 0)
                if input_p and output_p:
                    self._prices[model_id.lower()] = ModelPrice(
                        input_per_1m=float(input_p) * 1_000_000,
                        output_per_1m=float(output_p) * 1_000_000,
                    )

            # 写入缓存
            self._cache_file.parent.mkdir(parents=True, exist_ok=True)
            cache_data = {
                "timestamp": time.time(),
                "prices": {
                    k: {"input": v.input_per_1m, "output": v.output_per_1m}
                    for k, v in self._prices.items()
                },
            }
            self._cache_file.write_text(json.dumps(cache_data, indent=2))
            return True
        except Exception as e:
            logger.debug("Failed to fetch pricing from models.dev: %s", e)
            if self._mode == PricingMode.REQUIRED:
                raise RuntimeError(f"Failed to fetch pricing catalog: {e}") from e
            return False

    def _ensure_loaded(self) -> None:
        """确保定价数据已加载."""
        if self._loaded:
            return
        self._loaded = True

        # 1. 先加载 fallback
        self._load_bundled()

        # 2. 尝试缓存
        if self._load_cache():
            logger.debug("Loaded pricing from cache (%d models)", len(self._prices))
            return

        # 3. 尝试在线获取
        if self._fetch_online():
            logger.info("Loaded pricing from models.dev (%d models)", len(self._prices))
        else:
            logger.warning("Using bundled fallback pricing (%d models)", len(self._prices))

    def get_price(self, model_name: str) -> ModelPrice | None:
        """获取模型定价.

        Returns:
            ModelPrice or None if not found
        """
        self._ensure_loaded()
        model_lower = model_name.lower()

        # 精确匹配
        if model_lower in self._prices:
            return self._prices[model_lower]

        # 模糊匹配（去 provider prefix）
        for key, price in self._prices.items():
            if key in model_lower or model_lower in key:
                return price

        return None

    def get_cost(
        self,
        model_name: str,
        input_tokens: int,
        output_tokens: int,
    ) -> float:
        """计算调用成本（USD）."""
        price = self.get_price(model_name)
        if price is None:
            return 0.0
        return (
            input_tokens / 1_000_000 * price.input_per_1m
            + output_tokens / 1_000_000 * price.output_per_1m
        )

    def list_models(self) -> list[str]:
        """列出所有已知定价的模型."""
        self._ensure_loaded()
        return sorted(self._prices.keys())


_catalog: PricingCatalog | None = None


def get_catalog() -> PricingCatalog:
    """获取全局 PricingCatalog 单例."""
    global _catalog
    if _catalog is None:
        _catalog = PricingCatalog()
    return _catalog
