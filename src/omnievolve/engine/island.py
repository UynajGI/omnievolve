"""行为签名与 Island 管理.

S7-07: 实现行为签名接口与 demo
S7-10: 实现 IslandState 与岛内 archive
S7-11: 实现岛间迁移策略
S7-14: 实现停滞检测与跨分支触发
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@runtime_checkable
class BehaviorSignature(Protocol):
    """行为签名 Protocol.

    S7-07: 通过执行小样本获取候选的行为特征。
    """

    def compute(self, code: str, test_inputs: list[Any] | None = None) -> str:
        """计算行为签名.

        Args:
            code: 候选代码
            test_inputs: 测试输入

        Returns:
            行为签名（哈希字符串）
        """
        ...


class StaticBehaviorSignature:
    """静态行为签名 - 基于代码结构."""

    def compute(self, code: str, test_inputs: list[Any] | None = None) -> str:
        """基于 AST 和文本特征计算签名."""
        import ast

        features = []

        try:
            tree = ast.parse(code)
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    features.append(f"func:{node.name}:{len(node.args.args)}")
                elif isinstance(node, ast.ClassDef):
                    features.append(f"class:{node.name}")
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        features.append(f"import:{alias.name}")
        except SyntaxError:
            features.append("syntax_error")

        # 添加文本统计特征
        features.append(f"lines:{len(code.splitlines())}")
        features.append(f"chars:{len(code)}")

        return hashlib.sha256("|".join(sorted(features)).encode()).hexdigest()


@dataclass
class IslandState:
    """岛屿状态.

    S7-10: 每个岛屿维护独立的精英档案。
    """

    island_id: str
    candidates: list[str] = field(default_factory=list)
    elite_archive: list[tuple[str, float]] = field(default_factory=list)
    novelty_archive: list[tuple[str, float]] = field(default_factory=list)
    last_migration_gen: int = 0
    stagnation_count: int = 0
    historical_best_score: float | None = None
    _generation_best: dict[int, float] = field(default_factory=dict, repr=False)
    _generation_seen: set[int] = field(default_factory=set, repr=False)

    def add_candidate(self, candidate_id: str) -> None:
        """添加候选."""
        if candidate_id not in self.candidates:
            self.candidates.append(candidate_id)

    def update_elite(self, candidate_id: str, score: float) -> None:
        """更新精英档案."""
        # 检查是否已存在
        for i, (cid, _) in enumerate(self.elite_archive):
            if cid == candidate_id:
                if score > self.elite_archive[i][1]:
                    self.elite_archive[i] = (candidate_id, score)
                return

        self.elite_archive.append((candidate_id, score))
        self.elite_archive.sort(key=lambda x: x[1], reverse=True)

        # 保持档案大小
        if len(self.elite_archive) > 20:
            self.elite_archive = self.elite_archive[:20]

    def get_best(self) -> tuple[str, float] | None:
        """获取最佳候选."""
        if not self.elite_archive:
            return None
        return self.elite_archive[0]

    def get_elites(self, top_k: int = 3) -> list[tuple[str, float]]:
        """获取精英."""
        return self.elite_archive[:top_k]

    def update_novelty(self, candidate_id: str, novelty_score: float) -> None:
        """Maintain a task-score-independent novelty archive."""
        novelty = max(0.0, min(1.0, float(novelty_score)))
        self.novelty_archive = [
            (cid, score) for cid, score in self.novelty_archive if cid != candidate_id
        ]
        self.novelty_archive.append((candidate_id, novelty))
        self.novelty_archive.sort(key=lambda item: item[1], reverse=True)
        self.novelty_archive = self.novelty_archive[:20]

    def record_generation_score(self, generation: int, score: float, *, passed: bool) -> None:
        """Record one committed result without mutating stagnation yet."""
        self._generation_seen.add(generation)
        if not passed:
            return
        current = self._generation_best.get(generation)
        if current is None or score > current:
            self._generation_best[generation] = float(score)

    def finalize_generation(self, generation: int, *, tolerance: float = 1e-12) -> bool:
        """Update stagnation once from the generation-best score.

        Returns True only when this generation genuinely improved the island.
        """
        if generation not in self._generation_seen:
            return False
        self._generation_seen.discard(generation)
        generation_best = self._generation_best.pop(generation, None)
        improved = generation_best is not None and (
            self.historical_best_score is None
            or generation_best > self.historical_best_score + tolerance
        )
        if improved:
            self.historical_best_score = generation_best
            self.stagnation_count = 0
        else:
            self.stagnation_count += 1
        return improved


class IslandManager:
    """岛屿管理器.

    S7-10: 实现 IslandState 与岛内 archive
    S7-11: 实现岛间迁移策略
    S7-14: 实现停滞检测与跨分支触发
    """

    def __init__(
        self,
        *,
        num_islands: int = 4,
        migration_interval: int = 5,
        migration_size: int = 2,
    ) -> None:
        self._num_islands = num_islands
        self._migration_interval = migration_interval
        self._migration_size = migration_size
        self._islands: dict[str, IslandState] = {}
        self._migration_events: list[dict[str, Any]] = []

        # 初始化岛屿
        for i in range(num_islands):
            island_id = f"island_{i}"
            self._islands[island_id] = IslandState(island_id=island_id)

    def get_island(self, island_id: str) -> IslandState | None:
        """获取岛屿."""
        return self._islands.get(island_id)

    def get_all_islands(self) -> dict[str, IslandState]:
        """获取所有岛屿."""
        return self._islands

    def assign_candidate(self, candidate_id: str, island_id: str | None = None) -> str:
        """分配候选到岛屿.

        Returns:
            分配的岛屿 ID
        """
        if island_id and island_id in self._islands:
            self._islands[island_id].add_candidate(candidate_id)
            return island_id

        # 轮询分配
        import random

        island_ids = list(self._islands.keys())
        chosen = random.choice(island_ids)
        self._islands[chosen].add_candidate(candidate_id)
        return chosen

    def should_migrate(self, current_gen: int) -> bool:
        """检查是否应该进行迁移."""
        for island in self._islands.values():
            if current_gen - island.last_migration_gen >= self._migration_interval:
                return True
        return False

    def migrate(self, current_gen: int) -> list[tuple[str, str, str]]:
        """执行岛间迁移.

        S7-11: 将优秀候选迁移到其他岛屿。

        Returns:
            迁移记录列表 [(candidate_id, from_island, to_island), ...]
        """
        migrations: list[tuple[str, str, str]] = []

        # 收集每个岛屿的最佳候选
        island_bests = {}
        for island_id, island in self._islands.items():
            if island.elite_archive:
                island_bests[island_id] = island.elite_archive[: self._migration_size]

        if len(island_bests) < 2:
            return migrations

        # 环形迁移：每个岛屿的精英迁移到下一个岛屿
        island_ids = list(island_bests.keys())
        for i, source_id in enumerate(island_ids):
            target_id = island_ids[(i + 1) % len(island_ids)]

            for cand_id, score in island_bests[source_id]:
                # 在目标岛屿注册
                self._islands[target_id].add_candidate(cand_id)
                self._islands[target_id].update_elite(cand_id, score)

                migrations.append((cand_id, source_id, target_id))
                self._migration_events.append(
                    {
                        "candidate_id": cand_id,
                        "from_island": source_id,
                        "to_island": target_id,
                        "generation": current_gen,
                        "score": score,
                    }
                )

        # 更新迁移时间
        for island in self._islands.values():
            island.last_migration_gen = current_gen

        logger.info(f"Migration at gen {current_gen}: {len(migrations)} candidates moved")
        return migrations

    def detect_stagnation(
        self,
        threshold_gens: int = 5,
    ) -> list[str]:
        """检测停滞岛屿.

        S7-14: 实现停滞检测与跨分支触发。

        Returns:
            停滞的岛屿 ID 列表
        """
        stagnant = []
        for island_id, island in self._islands.items():
            if island.stagnation_count >= threshold_gens:
                stagnant.append(island_id)
        return stagnant

    def increment_stagnation(self, island_id: str) -> None:
        """增加停滞计数."""
        if island_id in self._islands:
            self._islands[island_id].stagnation_count += 1

    def reset_stagnation(self, island_id: str) -> None:
        """重置停滞计数（有改进时调用）."""
        if island_id in self._islands:
            self._islands[island_id].stagnation_count = 0

    def finalize_generation(self, generation: int, *, tolerance: float = 1e-12) -> dict[str, bool]:
        """Finalize generation-level stagnation for every island."""
        return {
            island_id: island.finalize_generation(generation, tolerance=tolerance)
            for island_id, island in self._islands.items()
        }

    def snapshot_state(self) -> dict[str, Any]:
        """Serialize island archives, stagnation and migration audit state."""
        return {
            "islands": {
                island_id: {
                    "candidates": list(island.candidates),
                    "elite_archive": [list(item) for item in island.elite_archive],
                    "novelty_archive": [list(item) for item in island.novelty_archive],
                    "last_migration_gen": island.last_migration_gen,
                    "stagnation_count": island.stagnation_count,
                    "historical_best_score": island.historical_best_score,
                    "generation_best": {
                        str(generation): score
                        for generation, score in island._generation_best.items()
                    },
                    "generation_seen": sorted(island._generation_seen),
                }
                for island_id, island in self._islands.items()
            },
            "migration_events": list(self._migration_events[-200:]),
        }

    def restore_state(self, state: dict[str, Any] | None) -> None:
        """Restore a checkpoint while accepting pre-state checkpoints."""
        if not state:
            return
        for island_id, payload in state.get("islands", {}).items():
            island = self._islands.get(island_id)
            if island is None:
                continue
            island.candidates = list(dict.fromkeys(payload.get("candidates", [])))
            island.elite_archive = [
                (str(candidate_id), float(score))
                for candidate_id, score in payload.get("elite_archive", [])
            ]
            island.novelty_archive = [
                (str(candidate_id), float(score))
                for candidate_id, score in payload.get("novelty_archive", [])
            ]
            island.last_migration_gen = int(payload.get("last_migration_gen", 0))
            island.stagnation_count = int(payload.get("stagnation_count", 0))
            historical = payload.get("historical_best_score")
            island.historical_best_score = float(historical) if historical is not None else None
            island._generation_best = {
                int(generation): float(score)
                for generation, score in payload.get("generation_best", {}).items()
            }
            island._generation_seen = {
                int(generation) for generation in payload.get("generation_seen", [])
            }
        self._migration_events = list(state.get("migration_events", []))[-200:]

    def get_stats(self) -> dict[str, Any]:
        """获取统计."""
        stats = {}
        for island_id, island in self._islands.items():
            best = island.get_best()
            stats[island_id] = {
                "candidates": len(island.candidates),
                "elite_size": len(island.elite_archive),
                "novelty_size": len(island.novelty_archive),
                "best_score": best[1] if best else None,
                "stagnation": island.stagnation_count,
            }
        return stats
