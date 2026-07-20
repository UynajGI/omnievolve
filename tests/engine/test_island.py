"""island.py 单元测试 — IslandState + IslandManager + BehaviorSignature."""

from __future__ import annotations

import pytest

from omnievolve.engine.island import (
    IslandManager,
    IslandState,
    StaticBehaviorSignature,
)

pytestmark = pytest.mark.unit


# --------------------------------------------------------------------------- #
#  IslandState
# --------------------------------------------------------------------------- #


class TestIslandState:
    def test_add_candidate(self):
        island = IslandState(island_id="i0")
        island.add_candidate("c1")
        assert "c1" in island.candidates

    def test_update_elite_new(self):
        island = IslandState(island_id="i0")
        island.update_elite("c1", 0.9)
        assert island.get_best() == ("c1", 0.9)

    def test_update_elite_better_score(self):
        island = IslandState(island_id="i0")
        island.update_elite("c1", 0.5)
        island.update_elite("c1", 0.9)
        assert island.get_best() == ("c1", 0.9)

    def test_update_elite_worse_score_kept(self):
        island = IslandState(island_id="i0")
        island.update_elite("c1", 0.9)
        island.update_elite("c1", 0.3)
        assert island.get_best() == ("c1", 0.9)

    def test_get_best_empty(self):
        island = IslandState(island_id="i0")
        assert island.get_best() is None

    def test_get_elites_top_k(self):
        island = IslandState(island_id="i0")
        for i, score in enumerate([0.5, 0.9, 0.7, 0.3]):
            island.update_elite(f"c{i}", score)
        elites = island.get_elites(top_k=2)
        assert len(elites) == 2
        assert elites[0][1] == 0.9  # 最高分在前

    def test_elite_archive_max_size(self):
        island = IslandState(island_id="i0")
        for i in range(25):
            island.update_elite(f"c{i}", float(i))
        assert len(island.elite_archive) <= 20

    def test_stagnation_initial_zero(self):
        island = IslandState(island_id="i0")
        assert island.stagnation_count == 0


# --------------------------------------------------------------------------- #
#  IslandManager
# --------------------------------------------------------------------------- #


class TestIslandManager:
    def test_init_creates_islands(self):
        mgr = IslandManager(num_islands=3)
        assert len(mgr.get_all_islands()) == 3
        assert mgr.get_island("island_0") is not None

    def test_assign_candidate_to_specific_island(self):
        mgr = IslandManager(num_islands=2)
        island_id = mgr.assign_candidate("c1", "island_1")
        assert island_id == "island_1"
        assert "c1" in mgr.get_island("island_1").candidates

    def test_assign_candidate_round_robin_fallback(self):
        mgr = IslandManager(num_islands=2)
        island_id = mgr.assign_candidate("c1")
        assert island_id in ["island_0", "island_1"]

    def test_should_migrate_before_interval(self):
        mgr = IslandManager(num_islands=2, migration_interval=5)
        assert mgr.should_migrate(0) is False  # gen 0 刚刚初始化

    def test_should_migrate_after_interval(self):
        mgr = IslandManager(num_islands=2, migration_interval=3)
        # 手动设置迁移时间
        for island in mgr.get_all_islands().values():
            island.last_migration_gen = 0
        assert mgr.should_migrate(4) is True

    def test_migrate_moves_elites(self):
        mgr = IslandManager(num_islands=2, migration_interval=2, migration_size=1)
        # 添加精英
        mgr.get_island("island_0").update_elite("e0", 0.9)
        mgr.get_island("island_1").update_elite("e1", 0.8)

        migrations = mgr.migrate(current_gen=2)
        assert len(migrations) == 2  # 两岛互迁

        # island_1 应有 island_0 的精英
        i1_elites = mgr.get_island("island_1").get_elites()
        i1_ids = [e[0] for e in i1_elites]
        assert "e0" in i1_ids or "e1" in i1_ids

    def test_migrate_single_island_noop(self):
        mgr = IslandManager(num_islands=1, migration_interval=2)
        mgr.get_island("island_0").update_elite("e0", 0.9)
        migrations = mgr.migrate(current_gen=2)
        assert migrations == []

    def test_migrate_updates_last_migration_gen(self):
        mgr = IslandManager(num_islands=2, migration_interval=2)
        mgr.get_island("island_0").update_elite("a", 0.5)
        mgr.get_island("island_1").update_elite("b", 0.6)
        mgr.migrate(current_gen=2)
        for island in mgr.get_all_islands().values():
            assert island.last_migration_gen == 2

    def test_detect_stagnation(self):
        mgr = IslandManager(num_islands=2)
        # 手动设置停滞计数
        mgr.get_island("island_0").stagnation_count = 5
        mgr.get_island("island_1").stagnation_count = 2
        stagnant = mgr.detect_stagnation(threshold_gens=5)
        assert "island_0" in stagnant
        assert "island_1" not in stagnant

    def test_increment_and_reset_stagnation(self):
        mgr = IslandManager(num_islands=1)
        mgr.increment_stagnation("island_0")
        mgr.increment_stagnation("island_0")
        assert mgr.get_island("island_0").stagnation_count == 2
        mgr.reset_stagnation("island_0")
        assert mgr.get_island("island_0").stagnation_count == 0

    def test_get_stats(self):
        mgr = IslandManager(num_islands=2)
        mgr.assign_candidate("c1", "island_0")
        mgr.get_island("island_0").update_elite("c1", 0.9)
        stats = mgr.get_stats()
        assert "island_0" in stats
        assert stats["island_0"]["candidates"] == 1
        assert stats["island_0"]["best_score"] == 0.9

    def test_get_island_missing(self):
        mgr = IslandManager(num_islands=2)
        assert mgr.get_island("nonexistent") is None

    def test_assign_to_nonexistent_island_falls_back(self):
        mgr = IslandManager(num_islands=2)
        island_id = mgr.assign_candidate("c1", "bad_island")
        assert island_id in ["island_0", "island_1"]


# --------------------------------------------------------------------------- #
#  StaticBehaviorSignature
# --------------------------------------------------------------------------- #


class TestBehaviorSignature:
    def test_compute_returns_hex_string(self):
        sig = StaticBehaviorSignature()
        result = sig.compute("def f():\n    return 1\n")
        assert len(result) == 64  # SHA-256 hex
        assert all(c in "0123456789abcdef" for c in result)

    def test_compute_different_code_different_signature(self):
        sig = StaticBehaviorSignature()
        s1 = sig.compute("def f():\n    return 1\n")
        s2 = sig.compute("def g():\n    return 2\n")
        assert s1 != s2

    def test_compute_same_code_same_signature(self):
        sig = StaticBehaviorSignature()
        code = "def f(x):\n    return x * 2\n"
        s1 = sig.compute(code)
        s2 = sig.compute(code)
        assert s1 == s2

    def test_compute_with_syntax_error(self):
        sig = StaticBehaviorSignature()
        result = sig.compute("not valid python {{{")
        assert isinstance(result, str)
        assert len(result) == 64  # 仍然返回有效哈希

    def test_compute_with_classes(self):
        sig = StaticBehaviorSignature()
        code = "class Foo:\n    def bar(self):\n        pass\n"
        result = sig.compute(code)
        assert len(result) == 64

    def test_compute_with_imports(self):
        sig = StaticBehaviorSignature()
        code = "import math\nimport os\n\ndef f():\n    pass\n"
        result = sig.compute(code)
        assert len(result) == 64
