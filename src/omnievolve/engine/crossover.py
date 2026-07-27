"""多父代跨分支融合.

S7-12: 实现 Crossover 多父代选择
"""

from __future__ import annotations

import logging
import random
from typing import Any

logger = logging.getLogger(__name__)


class CrossoverOperator:
    """多父代交叉算子.

    从多个高分候选中提取互补特征进行融合。
    """

    def __init__(
        self,
        *,
        min_parents: int = 2,
        max_parents: int = 3,
        similarity_threshold: float = 0.85,
    ) -> None:
        """初始化.

        Args:
            min_parents: 最少父代数
            max_parents: 最多父代数
            similarity_threshold: 血缘相似度阈值（太高则不交叉）
        """
        self._min_parents = min_parents
        self._max_parents = max_parents
        self._similarity_threshold = similarity_threshold

    def __repr__(self) -> str:
        return (
            f"CrossoverOperator(min_parents={self._min_parents}, "
            f"max_parents={self._max_parents}, "
            f"sim={self._similarity_threshold:.2f})"
        )

    @property
    def min_parents(self) -> int:
        """最少父代数（供引擎查询以决定选择数量）."""
        return self._min_parents

    def select_parents(
        self,
        candidates: list[tuple[str, float]],
        exclude_ids: list[str] | None = None,
    ) -> list[str]:
        """选择交叉父代.

        选择机制互补、血缘较远的候选。

        Args:
            candidates: [(candidate_id, score), ...]
            exclude_ids: 排除的候选 ID

        Returns:
            选中的父代 ID 列表
        """
        if len(candidates) < self._min_parents:
            return []

        # 过滤排除项
        if exclude_ids:
            candidates = [(cid, score) for cid, score in candidates if cid not in exclude_ids]

        # 按分数排序
        sorted_candidates = sorted(candidates, key=lambda x: x[1], reverse=True)

        # 从高分候选中随机选择
        pool_size = min(len(sorted_candidates), self._max_parents * 2)
        pool = sorted_candidates[:pool_size]

        num_parents = random.randint(self._min_parents, min(self._max_parents, len(pool)))
        selected = random.sample(pool, num_parents)

        return [c[0] for c in selected]

    def combine(
        self,
        parent_codes: list[str],
        strategy: str = "segment",
        *,
        code_store: Any = None,
        parent_refs: list[str] | None = None,
    ) -> str:
        """融合多个父代代码.

        Args:
            parent_codes: 父代代码列表
            strategy: 融合策略 (segment/function_level/feature_merge)
            code_store: CodeStore 实例（Git 后端优先尝试 merge）
            parent_refs: 父代 ref 列表（用于 Git merge）

        Returns:
            融合后的代码
        """
        if len(parent_codes) == 1:
            return parent_codes[0]

        # Git 后端: 优先尝试 git merge crossover
        if code_store and parent_refs and len(parent_refs) >= 2:
            merged = code_store.merge(parent_refs)
            if merged is not None:
                try:
                    return code_store.load_snapshot(merged)
                except Exception:
                    logger.debug(
                        "Git merge load failed, falling back to text crossover", exc_info=True
                    )

        # Fallback: 文本/AST 策略
        if strategy == "segment":
            return self._segment_crossover(parent_codes)
        elif strategy == "function_level":
            return self._function_level_crossover(parent_codes)
        else:
            return self._feature_merge(parent_codes)

    def _segment_crossover(self, codes: list[str]) -> str:
        """段交叉 - 按行段交叉."""
        all_lines = []
        for code in codes:
            lines = code.strip().split("\n")
            all_lines.append(lines)

        # 选择交叉点
        min_len = min(len(lines) for lines in all_lines)
        if min_len <= 1:
            return random.choice(codes)

        crossover_point = random.randint(1, min_len - 1)

        # 从第一个父代取前半部分，第二个取后半
        result = all_lines[0][:crossover_point] + all_lines[1][crossover_point:]
        return "\n".join(result)

    def _function_level_crossover(self, codes: list[str]) -> str:
        """函数级交叉 - 从不同父代提取函数."""
        import ast

        all_functions = {}
        imports = set()

        for code in codes:
            try:
                tree = ast.parse(code)
                for node in ast.walk(tree):
                    if isinstance(node, ast.FunctionDef):
                        all_functions[node.name] = ast.get_source_segment(code, node)
                    elif isinstance(node, ast.Import):
                        for alias in node.names:
                            imports.add(f"import {alias.name}")
                    elif isinstance(node, ast.ImportFrom):
                        if node.module:
                            imports.add(
                                f"from {node.module} import {', '.join(a.name for a in node.names)}"
                            )
            except SyntaxError:
                continue

        # 组装结果
        parts = list(imports)
        for func_name, func_code in all_functions.items():
            if func_code is not None:
                parts.append(func_code)

        return "\n\n".join(parts)

    def _feature_merge(self, codes: list[str]) -> str:
        """特征合并 - 保留所有父代的独特特征."""
        # 简化：使用最长代码作为基础，添加其他代码的独特函数
        sorted_codes = sorted(codes, key=len, reverse=True)
        base = sorted_codes[0]

        # 尝试解析并添加新函数
        try:
            import ast

            base_tree = ast.parse(base)
            base_funcs = {
                node.name for node in ast.walk(base_tree) if isinstance(node, ast.FunctionDef)
            }

            for code in sorted_codes[1:]:
                tree = ast.parse(code)
                for node in ast.walk(tree):
                    if isinstance(node, ast.FunctionDef) and node.name not in base_funcs:
                        func_code = ast.get_source_segment(code, node)
                        if func_code:
                            base += f"\n\n{func_code}"
                            base_funcs.add(node.name)

        except SyntaxError:
            pass

        return base
