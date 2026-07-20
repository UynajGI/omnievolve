"""全局种子管理器测试."""

from __future__ import annotations

import random

from omnievolve.utils.seed import (
    derive_component_seed,
    get_global_seed,
    reset_seeds,
    seed_context,
    set_global_seed,
)


class TestSeedManager:
    """种子管理测试."""

    def setup_method(self) -> None:
        reset_seeds()

    def test_set_global_seed_default(self) -> None:
        seed = set_global_seed()
        assert seed == 42

    def test_set_global_seed_explicit(self) -> None:
        seed = set_global_seed(12345)
        assert seed == 12345
        assert get_global_seed() == 12345

    def test_derive_component_seed_deterministic(self) -> None:
        set_global_seed(42)
        s1 = derive_component_seed("mcts")
        s2 = derive_component_seed("mcts")
        assert s1 == s2, "同一组件应返回相同种子"

    def test_derive_component_seed_different_components(self) -> None:
        set_global_seed(42)
        s1 = derive_component_seed("mcts")
        s2 = derive_component_seed("crossover")
        assert s1 != s2, "不同组件应返回不同种子"

    def test_derive_component_seed_different_base(self) -> None:
        s1 = derive_component_seed("mcts", base_seed=42)
        s2 = derive_component_seed("mcts", base_seed=99)
        assert s1 != s2, "不同基础种子应产生不同派生种子"

    def test_seed_context(self) -> None:
        set_global_seed(77)
        derive_component_seed("mcts")
        ctx = seed_context(77)
        assert ctx["global_seed"] == 77
        assert ctx["requested_seed"] == 77
        assert "component_seeds" in ctx
        assert isinstance(ctx["random_state"], tuple)

    def test_set_global_seed_sets_random_state(self) -> None:
        set_global_seed(42)
        val1 = random.random()
        set_global_seed(42)
        val2 = random.random()
        assert val1 == val2, "相同种子产生相同序列"

    def test_get_global_seed_default(self) -> None:
        assert get_global_seed() == 42
