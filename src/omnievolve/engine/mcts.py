"""渐进式 MCGS (Monte-Carlo Graph Search).

S7-15: 实现轻量 Progressive MCGS 占位
- UCB 选择
- 虚拟损失
- 子图回写
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class MCTSNode:
    """MCTS 节点."""

    candidate_id: str
    parent: str | None = None
    children: list[str] = field(default_factory=list)
    visit_count: int = 0
    value_sum: float = 0.0
    prior: float = 0.0
    virtual_loss: float = 0.0

    @property
    def mean_value(self) -> float:
        if self.visit_count == 0:
            return 0.0
        return self.value_sum / self.visit_count

    def ucb1(self, exploration: float = 1.414, total_visits: int = 1) -> float:
        """UCB1 值."""
        if self.visit_count == 0:
            return float("inf")
        exploitation = self.mean_value
        exploration_term = exploration * math.sqrt(
            math.log(max(total_visits, 1)) / self.visit_count
        )
        return exploitation + exploration_term - self.virtual_loss

    def ppt(self, c_puct: float = 1.0, total_visits: int = 1) -> float:
        """PUCT (Predictor + UCB applied to trees) 值."""
        if self.visit_count == 0:
            q_value = 0.0
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
    ) -> None:
        self._exploration = exploration
        self._c_puct = c_puct
        self._virtual_loss = virtual_loss
        self._selection_policy = selection_policy
        self._nodes: dict[str, MCTSNode] = {}

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
                    score = child.ucb1(self._exploration, total_visits)

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
        """回传阶段.

        Args:
            leaf_id: 叶节点 ID
            value: 评估值
        """
        current = leaf_id

        while current is not None:
            node = self._nodes.get(current)
            if node is None:
                break

            node.visit_count += 1
            node.value_sum += value
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
