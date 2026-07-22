"""Epiplexity — 可学习新奇性估计器.

基于 LEARNABLE_NOVELTY (2607.18433) 论文:
- 任务无关的候选代码质量信号
- 同时免疫"噪声电视"（纯随机）和"暗室"（纯重复）
- 奖励"对有界观察者来说可学习的新结构"

实现原理:
    S_φ(code) = 结构丰富性 × 可压缩性 × 新颖性

    - 结构丰富性: AST 节点类型多样性（太简单→0，太随机→低）
    - 可压缩性: gzip 压缩比（随机→~1，有结构→<1，平凡→极低）
    - 新颖性: 与历史候选的结构距离（重复→0）

    最终分数在"临界复杂度"处取最大值:
    - 平凡代码（常数、恒等映射）→ ≈ 0
    - 随机代码（无结构噪声）→ ≈ 0
    - 临界代码（有结构但非平凡）→ 最大

使用场景:
    1. NoveltyGate 预筛选（比 embedding 更廉价）
    2. 辅助适应度维度（奖励结构丰富性）
    3. 进化停滞检测（所有候选 epiplexity 下降 → 搜索饱和）
"""

from __future__ import annotations

import ast
import gzip
import hashlib
import logging
import math
from collections import Counter

logger = logging.getLogger(__name__)


class EpiplexityEstimator:
    """可学习新奇性估计器.

    闭式计算（无需 LLM 调用），复杂度 O(n) 于代码长度。
    """

    def __init__(
        self,
        *,
        history_size: int = 100,
        richness_weight: float = 0.4,
        compressibility_weight: float = 0.3,
        novelty_weight: float = 0.3,
    ) -> None:
        """初始化.

        Args:
            history_size: 保留多少历史签名用于新颖性比较
            richness_weight: 结构丰富性权重
            compressibility_weight: 可压缩性权重
            novelty_weight: 新颖性权重
        """
        self._history_size = history_size
        self._w_richness = richness_weight
        self._w_compress = compressibility_weight
        self._w_novelty = novelty_weight
        # 历史结构签名（用于新颖性计算）
        self._history: list[str] = []

    def score(self, code: str) -> float:
        """计算代码的可学习新奇性分数.

        Args:
            code: 源代码字符串

        Returns:
            分数 ∈ [0, 1]，临界复杂度处取最大值
        """
        if not code or not code.strip():
            return 0.0

        richness = self._structural_richness(code)
        compressibility = self._compressibility_score(code)
        novelty = self._novelty_score(code)

        # 加权组合
        score = (
            self._w_richness * richness
            + self._w_compress * compressibility
            + self._w_novelty * novelty
        )

        # 记录到历史
        sig = self._compute_signature(code)
        self._history.append(sig)
        if len(self._history) > self._history_size:
            self._history = self._history[-self._history_size :]

        return max(0.0, min(1.0, score))

    def _structural_richness(self, code: str) -> float:
        """结构丰富性 — AST 节点类型多样性.

        论文映射: 太简单→无结构可学→0，太复杂→不可学习→低
        实现: 使用节点类型多样性的归一化熵，在中等复杂度处取最大值。
        """
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return 0.0

        # 收集 AST 节点类型
        node_types = [type(node).__name__ for node in ast.walk(tree)]
        if not node_types:
            return 0.0

        # 节点类型多样性（归一化 Shannon 熵）
        type_counts = Counter(node_types)
        n_types = len(type_counts)
        n_total = len(node_types)

        if n_types <= 1:
            return 0.0  # 只有一种节点类型 → 平凡

        # Shannon 熵
        entropy = 0.0
        for count in type_counts.values():
            p = count / n_total
            if p > 0:
                entropy -= p * math.log2(p)

        # 归一化到 [0, 1]
        max_entropy = math.log2(n_types)
        normalized_entropy = entropy / max_entropy if max_entropy > 0 else 0.0

        # 结构复杂度（节点总数对数缩放）
        complexity = math.log2(max(n_total, 1)) / 10.0  # ~1000 节点 → 1.0
        complexity = min(complexity, 1.0)

        # 临界性: 熵 × 复杂度的几何均值（两者都中等时最大）
        richness = math.sqrt(normalized_entropy * complexity)

        return richness

    def _compressibility_score(self, code: str) -> float:
        """可压缩性分数 — 有结构但非平凡.

        论文映射:
        - 随机代码: 压缩比 ≈ 1.0 → 不可学习 → 低分
        - 平凡代码: 压缩比 ≈ 0.1 → 无新结构 → 低分
        - 临界代码: 压缩比 ≈ 0.3-0.6 → 有结构可学 → 高分

        使用倒 U 形函数，在压缩比 ≈ 0.4 处取最大值。
        """
        code_bytes = code.encode("utf-8")
        if not code_bytes:
            return 0.0

        compressed = gzip.compress(code_bytes, compresslevel=6)
        ratio = len(compressed) / len(code_bytes)

        # 倒 U 形: 在 ratio ≈ 0.4 处取最大值
        # 使用高斯函数: exp(-(ratio - center)^2 / (2 * sigma^2))
        center = 0.4
        sigma = 0.25
        score = math.exp(-((ratio - center) ** 2) / (2 * sigma**2))

        return score

    def _novelty_score(self, code: str) -> float:
        """新颖性 — 与历史候选的结构距离.

        论文映射: 重复→无新结构可学→0，全新→最大可学习潜力→1
        """
        if not self._history:
            return 1.0  # 无历史时默认新颖

        sig = self._compute_signature(code)

        # 计算与历史签名的最小距离
        # 使用 Jaccard 距离的简化版本
        sig_tokens = set(sig.split("|"))
        min_similarity = 1.0

        for hist_sig in self._history[-20:]:  # 只比较最近 20 个
            hist_tokens = set(hist_sig.split("|"))
            if not sig_tokens or not hist_tokens:
                continue
            intersection = len(sig_tokens & hist_tokens)
            union = len(sig_tokens | hist_tokens)
            similarity = intersection / union if union > 0 else 0.0
            min_similarity = min(min_similarity, 1.0 - similarity)

        # min_similarity 越小 = 与历史越相似 = 越不新颖
        # 返回新颖性分数
        return 1.0 - min_similarity if min_similarity < 1.0 else 0.5

    @staticmethod
    def _compute_signature(code: str) -> str:
        """计算代码结构签名（用于新颖性比较）."""
        try:
            tree = ast.parse(code)
            # 提取函数/类名 + 节点类型序列
            parts = []
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                    parts.append(f"{type(node).__name__}:{node.name}")
                elif isinstance(node, (ast.Import, ast.ImportFrom)):
                    parts.append(type(node).__name__)
                else:
                    parts.append(type(node).__name__)
            return "|".join(parts[:50])  # 限制长度
        except SyntaxError:
            return hashlib.md5(code.encode()).hexdigest()

    def batch_score(self, codes: list[str]) -> list[float]:
        """批量计算分数."""
        return [self.score(code) for code in codes]

    def get_stats(self) -> dict:
        """获取估计器统计."""
        return {
            "history_size": len(self._history),
            "max_history": self._history_size,
        }
