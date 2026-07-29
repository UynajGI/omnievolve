"""Lineage-aware UCB search.

This implementation follows one primary-parent lineage and performs no
rollout over a general DAG.  ``LineageUCB`` is therefore the canonical,
research-honest name.  ``ProgressiveMCGS`` remains a compatibility alias.

S7-15: 实现轻量 lineage UCB
- UCB / PUCT 选择
- Beta 回传（Bayesian value estimation）
- 虚拟损失
- 子图回写

P1-1: 分段衰减探索常数 C(t)
P1-3: 强制反向传播（后期加速收敛 + 多样性）

Beta 回传（Bayesian backpropagation）是核心设计原则：
不使用 frequentist mean (value_sum / visit_count)，而是维护 Beta 分布
参数 alpha / beta。这使得：
1. 少量访问的节点保留不确定性（宽后验），不会因单次低分被剪枝
2. UCB exploration term + Beta uncertainty → 自然探索“1+1>2”组合分支
3. 高分组合（单独差但配对好）不会被过早收敛
"""

from __future__ import annotations

import logging
import math
import random
import threading
import warnings
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class MCTSNode:
    """MCTS 节点（Beta 回传）."""

    candidate_id: str
    parent: str | None = None
    children: list[str] = field(default_factory=list)
    visit_count: int = 0
    value_sum: float = 0.0
    prior: float = 0.0
    virtual_loss: float = 0.0
    # Beta 分布参数（Beta(α, β) 后验）
    # 先验：Beta(1, 1) = Uniform[0,1]，表示"无信息"
    alpha: float = 1.0
    beta: float = 1.0

    @property
    def mean_value(self) -> float:
        """Beta 分布后验均值 α/(α+β).

        比 frequentist mean (value_sum/visit_count) 更好地处理不确定性：
        - 少量访问时趋近先验 0.5（保守）
        - 大量访问时趋近真实值
        - 从不高估或低估单次极端结果
        """
        return self.alpha / (self.alpha + self.beta)

    @property
    def beta_variance(self) -> float:
        """Beta 分布方差 αβ / ((α+β)²(α+β+1)).

        用于不确定性量化和 exploration bonus。
        """
        s = self.alpha + self.beta
        return (self.alpha * self.beta) / (s * s * (s + 1))

    @property
    def raw_mean(self) -> float:
        """Frequentist mean（保留用于统计/调试）."""
        if self.visit_count == 0:
            return 0.0
        return self.value_sum / self.visit_count

    def update_beta(self, reward: float, weight: float = 1.0) -> None:
        """Beta 分布更新.

        对于连续 reward ∈ [0, 1]：
            alpha += reward        （成功质量）
            beta += (1 - reward)   （失败质量）

        这等价于将 reward 视为 Bernoulli 试验的成功概率，
        进行 soft Bayesian update。

        对于 reward 超出 [0,1] 的情况，先 clamp。
        """
        r = max(0.0, min(1.0, reward))
        w = max(0.0, weight)
        self.alpha += w * r
        self.beta += w * (1.0 - r)

    def ucb1(self, exploration: float = 1.414, total_visits: int = 1) -> float:
        """UCB1 值（使用 Beta 后验均值）."""
        if self.visit_count == 0:
            return float("inf")
        exploitation = self.mean_value
        exploration_term = exploration * math.sqrt(
            math.log(max(total_visits, 1)) / self.visit_count
        )
        return exploitation + exploration_term - self.virtual_loss

    def ppt(self, c_puct: float = 1.0, total_visits: int = 1) -> float:
        """PUCT (Predictor + UCB applied to trees) 值（使用 Beta 后验均值）."""
        if self.visit_count == 0:
            q_value = 0.5  # 先验均值，而非 0
        else:
            q_value = self.mean_value

        u_value = c_puct * self.prior * math.sqrt(total_visits) / (1 + self.visit_count)
        return q_value + u_value - self.virtual_loss


class LineageUCB:
    """Progressive UCB over a primary-parent lineage.

    在候选图上进行搜索，而非固定的树结构。
    支持多父代 DAG 和虚拟损失。

    T2: 内存修剪 — 调用 prune(db) 删除 closed/pruned 的叶子节点，
    保留 elite 和 max_nodes 个最活跃节点。
    """

    def __init__(
        self,
        *,
        exploration: float = 1.414,
        c_puct: float = 1.0,
        virtual_loss: float = 1.0,
        selection_policy: str = "ucb1",  # ucb1 / puct
        schedule: str = "constant",  # constant / progressive
        c_min: float = 0.2,
        decay_point: float = 0.5,  # P1-1: 衰减完成点（进度比例）
        max_nodes: int = 5000,
    ) -> None:
        self._exploration = exploration
        self._c_max = exploration
        self._c_min = c_min
        self._decay_point = decay_point  # P1-1
        self._c_puct = c_puct
        self._virtual_loss = virtual_loss
        self._selection_policy = selection_policy
        self._schedule = schedule
        self._progress: float = 0.0  # 0.0 → 1.0
        self._nodes: dict[str, MCTSNode] = {}
        self._max_nodes = max_nodes
        # 线程局部存储：并行 prepare() 时各线程独立记录 select 路径
        self._select_local = threading.local()
        # P1-3: 强制反向传播计数器
        self._nodes_since_backprop: int = 0
        self._backprop_lock = threading.Lock()

    @property
    def effective_exploration(self) -> float:
        """P1-1: 当前有效的 exploration 常数（分段衰减）.

        C(t) = C_max - (C_max - C_min) * min(progress / decay_point, 1.0)
        当 progress >= decay_point 时，C 达到 C_min 并保持不变。
        """
        if self._schedule == "progressive":
            decay_ratio = min(self._progress / max(self._decay_point, 1e-9), 1.0)
            return self._c_max - (self._c_max - self._c_min) * decay_ratio
        return self._exploration

    def set_progress(self, generation: int, max_generations: int) -> None:
        """设置搜索进度（0.0 → 1.0），用于渐进探索衰减.

        由 EvolutionEngine 每代调用。
        """
        if max_generations > 0:
            self._progress = min(1.0, generation / max_generations)
        else:
            self._progress = 0.0

    def should_force_backprop(self) -> bool:
        """P1-3: 判断是否应强制反向传播.

        策略（参考 MLEvolve）：
        - 后期（>80% progress）：50% 概率直接反向传播
        - 中期（>40% progress）：每 3 个节点反向传播一次
        - 早期：不强制

        前置条件：搜索树必须有足够节点（>=5），避免小规模运行被跳过。
        """
        # 前置条件：搜索树节点不足时不触发（避免跳过早期候选）
        if len(self._nodes) < 5:
            return False
        if self._progress > 0.8:
            return random.random() < 0.5
        if self._progress > 0.4:
            with self._backprop_lock:
                self._nodes_since_backprop += 1
                if self._nodes_since_backprop >= 3:
                    self._nodes_since_backprop = 0
                    return True
        return False

    def force_backprop(self, node_id: str, value: float = 0.0) -> None:
        """P1-3: 强制反向传播（不继续 improve 链，直接回传）.

        对节点及其祖先链执行 visit_count += 1 更新，
        不改变 Beta 参数（因为无真实评估结果）。
        """
        current: str | None = node_id
        while current is not None:
            node = self._nodes.get(current)
            if node is None:
                break
            node.visit_count += 1
            # 清除 select() 期间累加的虚拟损失
            node.virtual_loss = max(0.0, node.virtual_loss - self._virtual_loss)
            current = node.parent

    def add_node(
        self,
        candidate_id: str,
        parent: str | None = None,
        prior: float = 0.0,
    ) -> MCTSNode:
        """添加节点."""
        if candidate_id not in self._nodes:
            node = MCTSNode(
                candidate_id=candidate_id,
                parent=parent,
                prior=prior,
            )
            self._nodes[candidate_id] = node

            if parent and parent in self._nodes:
                self._nodes[parent].children.append(candidate_id)

        return self._nodes[candidate_id]

    def select(self, root_id: str) -> str:
        """选择阶段 - 从根节点选择到叶节点.

        Returns:
            选中的叶节点 ID
        """
        current = root_id
        self._select_local.path = []

        while True:
            node = self._nodes.get(current)
            if node is None or not node.children:
                return current

            # 应用虚拟损失
            node.virtual_loss += self._virtual_loss
            self._select_local.path.append(current)

            # 选择最优子节点
            total_visits = (
                sum(self._nodes[c].visit_count for c in node.children if c in self._nodes) + 1
            )

            best_child = None
            best_score = -float("inf")

            for child_id in node.children:
                child = self._nodes.get(child_id)
                if child is None:
                    continue

                if self._selection_policy == "puct":
                    score = child.ppt(self._c_puct, total_visits)
                else:
                    score = child.ucb1(self.effective_exploration, total_visits)

                if score > best_score:
                    best_score = score
                    best_child = child_id

            if best_child is None:
                return current

            current = best_child

    def expand(
        self,
        parent_id: str,
        children: list[tuple[str, float]],
    ) -> list[str]:
        """扩展阶段.

        Args:
            parent_id: 父节点 ID
            children: [(candidate_id, prior), ...]

        Returns:
            新增的子节点 ID 列表
        """
        added = []
        for child_id, prior in children:
            if child_id not in self._nodes:
                self.add_node(child_id, parent=parent_id, prior=prior)
                added.append(child_id)
            elif parent_id in self._nodes:
                # 已存在节点，添加边
                if child_id not in self._nodes[parent_id].children:
                    self._nodes[parent_id].children.append(child_id)
        return added

    def backpropagate(
        self,
        leaf_id: str,
        value: float,
    ) -> None:
        """回传阶段（Beta Bayesian update）.

        对路径上的每个节点：
        1. 更新 visit_count / value_sum（保留 frequentist 统计）
        2. 更新 Beta(alpha, beta) 后验参数（Bayesian 价值估计）

        Args:
            leaf_id: 叶节点 ID
            value: 评估值（自动 clamp 到 [0,1]）
        """
        current: str | None = leaf_id

        while current is not None:
            node = self._nodes.get(current)
            if node is None:
                break

            # Frequentist 统计（保留用于调试/监控）
            node.visit_count += 1
            node.value_sum += value

            # Beta Bayesian 更新（核心：使搜索决策基于后验均值而非频率均值）
            node.update_beta(value)

            # 清除虚拟损失
            node.virtual_loss = max(0, node.virtual_loss - self._virtual_loss)

            current = node.parent

    def credit_references(
        self,
        reference_ids: list[str],
        value: float,
        *,
        weight: float = 0.25,
        exclude_ids: set[str] | None = None,
    ) -> list[str]:
        """给非树 reference edge 的源节点分配折扣信用.

        Reference credit 只更新 Beta 后验，不增加真实访问次数，也不沿
        reference 节点的祖先继续传播，从而避免 DAG 多路径重复计权。
        """
        excluded = exclude_ids or set()
        credited: list[str] = []
        for reference_id in dict.fromkeys(reference_ids):
            if reference_id in excluded:
                continue
            node = self._nodes.get(reference_id)
            if node is None:
                continue
            node.update_beta(value, weight=weight)
            credited.append(reference_id)
        return credited

    def get_best_child(self, node_id: str) -> str | None:
        """获取最优子节点（按访问次数）."""
        node = self._nodes.get(node_id)
        if node is None or not node.children:
            return None

        best = max(
            node.children,
            key=lambda c: self._nodes[c].visit_count if c in self._nodes else 0,
        )
        return best

    def get_stats(self) -> dict[str, Any]:
        """获取统计."""
        total_visits = sum(n.visit_count for n in self._nodes.values())
        return {
            "algorithm": "lineage_ucb",
            "nodes": len(self._nodes),
            "total_visits": total_visits,
            "avg_value": (
                sum(n.mean_value for n in self._nodes.values()) / len(self._nodes)
                if self._nodes
                else 0.0
            ),
        }

    def snapshot_state(self) -> dict[str, Any]:
        """Serialize adaptive search state for deterministic resume."""
        return {
            "algorithm": "lineage_ucb",
            "progress": self._progress,
            "nodes_since_backprop": self._nodes_since_backprop,
            "nodes": {
                candidate_id: {
                    "parent": node.parent,
                    "children": list(node.children),
                    "visit_count": node.visit_count,
                    "value_sum": node.value_sum,
                    "prior": node.prior,
                    # Virtual loss is transient and must not survive a completed generation.
                    "alpha": node.alpha,
                    "beta": node.beta,
                }
                for candidate_id, node in self._nodes.items()
            },
        }

    def restore_state(self, state: dict[str, Any] | None) -> None:
        """Restore state while accepting checkpoints created before this schema."""
        if not state:
            return
        self._progress = float(state.get("progress", self._progress))
        self._nodes_since_backprop = int(state.get("nodes_since_backprop", 0))
        restored: dict[str, MCTSNode] = {}
        for candidate_id, payload in state.get("nodes", {}).items():
            restored[candidate_id] = MCTSNode(
                candidate_id=candidate_id,
                parent=payload.get("parent"),
                children=list(payload.get("children", [])),
                visit_count=int(payload.get("visit_count", 0)),
                value_sum=float(payload.get("value_sum", 0.0)),
                prior=float(payload.get("prior", 0.0)),
                virtual_loss=0.0,
                alpha=float(payload.get("alpha", 1.0)),
                beta=float(payload.get("beta", 1.0)),
            )
        if restored:
            self._nodes = restored

    def rollback_last_select(self) -> None:
        """回滚上次 select() 路径上的虚拟损失.

        当候选被 Novelty/Critic 拒绝而不会 backpropagate 时调用，
        避免虚拟损失永久累积损害搜索多样性。
        """
        for node_id in getattr(self._select_local, "path", []):
            node = self._nodes.get(node_id)
            if node:
                node.virtual_loss = max(0.0, node.virtual_loss - self._virtual_loss)
        self._select_local.path = []
        self._nodes_since_backprop = 0

    def clear_virtual_losses(self) -> None:
        """清除所有虚拟损失."""
        for node in self._nodes.values():
            node.virtual_loss = 0.0

    def prune(self, db: Any) -> dict[str, int]:
        """内存修剪 — 删除低价值节点，保留 elite 和活跃节点。

        策略：
        1. 从 DB 读取 frontier_status，删除 closed/pruned 的叶子
        2. 如果节点数仍超 max_nodes，按 visit_count 升序淘汰

        Returns:
            {"before": N, "after": M, "pruned": K}
        """
        if len(self._nodes) <= self._max_nodes:
            return {"before": len(self._nodes), "after": len(self._nodes), "pruned": 0}

        before = len(self._nodes)

        # 1. 从 DB 获取可修剪的候选（closed/pruned）
        prunable_ids: set[str] = set()
        try:
            rows = db.fetchall(
                """
                SELECT candidate_id, frontier_status
                FROM candidate_search_state
                WHERE candidate_id IN ({})
                """.format(",".join(["?"] * len(self._nodes))),
                tuple(self._nodes.keys()),
            )
            for row in rows:
                status = row["frontier_status"] or "open"
                if status in ("closed", "pruned"):
                    cid = row["candidate_id"]
                    node = self._nodes.get(cid)
                    # 只删叶子节点（没有子节点引用的）
                    if node and not node.children:
                        prunable_ids.add(cid)
        except Exception:
            logger.debug("MCTS prune: DB query failed, skipping", exc_info=True)

        # 2. 执行删除 + 清理父节点的 children 引用
        for cid in prunable_ids:
            node = self._nodes.pop(cid, None)
            if node and node.parent and node.parent in self._nodes:
                parent = self._nodes[node.parent]
                parent.children = [c for c in parent.children if c != cid]

        # 3. 如果仍超限，按 visit_count 升序淘汰叶子
        if len(self._nodes) > self._max_nodes:
            leaf_nodes = [(cid, node) for cid, node in self._nodes.items() if not node.children]
            leaf_nodes.sort(key=lambda x: x[1].visit_count)
            excess = len(self._nodes) - self._max_nodes
            for cid, node in leaf_nodes[:excess]:
                self._nodes.pop(cid, None)
                if node.parent and node.parent in self._nodes:
                    parent = self._nodes[node.parent]
                    parent.children = [c for c in parent.children if c != cid]

        after = len(self._nodes)
        logger.info("MCTS pruned: %d → %d nodes (%d removed)", before, after, before - after)
        return {"before": before, "after": after, "pruned": before - after}


class ProgressiveMCGS(LineageUCB):
    """Deprecated compatibility name for :class:`LineageUCB`."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        warnings.warn(
            "ProgressiveMCGS is a compatibility name; use LineageUCB",
            DeprecationWarning,
            stacklevel=2,
        )
        super().__init__(*args, **kwargs)
