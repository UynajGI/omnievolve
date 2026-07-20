"""渐进式 MCGS (Monte-Carlo Graph Search).

S7-15: 实现轻量 Progressive MCGS
- UCB / PUCT 选择
- Beta 回传（Bayesian value estimation）
- 虚拟损失
- 子图回写

Beta 回传（Bayesian backpropagation）是核心设计原则：
不使用 frequentist mean (value_sum / visit_count)，而是维护 Beta 分布
参数 alpha / beta。这使得：
1. 少量访问的节点保留不确定性（宽后验），不会因单次低分被剪枝
2. UCB exploration term + Beta uncertainty → 自然探索"1+1>2"组合分支
3. 高分组合（单独差但配对好）不会被过早收敛
"""

from __future__ import annotations

import logging
import math
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

    def update_beta(self, reward: float) -> None:
        """Beta 分布更新.

        对于连续 reward ∈ [0, 1]：
            alpha += reward        （成功质量）
            beta += (1 - reward)   （失败质量）

        这等价于将 reward 视为 Bernoulli 试验的成功概率，
        进行 soft Bayesian update。

        对于 reward 超出 [0,1] 的情况，先 clamp。
        """
        r = max(0.0, min(1.0, reward))
        self.alpha += r
        self.beta += 1.0 - r

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


class ProgressiveMCGS:
    """渐进式 Monte-Carlo Graph Search.

    在候选图上进行搜索，而非固定的树结构。
    支持多父代 DAG 和虚拟损失。
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
    ) -> None:
        self._exploration = exploration
        self._c_max = exploration
        self._c_min = c_min
        self._c_puct = c_puct
        self._virtual_loss = virtual_loss
        self._selection_policy = selection_policy
        self._schedule = schedule
        self._progress: float = 0.0  # 0.0 → 1.0
        self._nodes: dict[str, MCTSNode] = {}

    @property
    def effective_exploration(self) -> float:
        """当前有效的 exploration 常数（考虑渐进衰减）."""
        if self._schedule == "progressive":
            # c(p) = c_max - (c_max - c_min) * progress
            return self._c_max - (self._c_max - self._c_min) * self._progress
        return self._exploration

    def set_progress(self, generation: int, max_generations: int) -> None:
        """设置搜索进度（0.0 → 1.0），用于渐进探索衰减.

        由 EvolutionEngine 每代调用。
        """
        if max_generations > 0:
            self._progress = min(1.0, generation / max_generations)
        else:
            self._progress = 0.0

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

        while True:
            node = self._nodes.get(current)
            if node is None or not node.children:
                return current

            # 应用虚拟损失
            node.virtual_loss += self._virtual_loss

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
            "nodes": len(self._nodes),
            "total_visits": total_visits,
            "avg_value": (
                sum(n.mean_value for n in self._nodes.values()) / len(self._nodes)
                if self._nodes
                else 0.0
            ),
        }

    def clear_virtual_losses(self) -> None:
        """清除所有虚拟损失."""
        for node in self._nodes.values():
            node.virtual_loss = 0.0
