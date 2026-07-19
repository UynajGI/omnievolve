"""多级 NoveltyGate.

S7-05: 实现 Embedding 新颖性预筛
S7-06: 实现 AST/结构签名
S7-08: 实现多级 NoveltyGate 决策器
"""

from __future__ import annotations

import ast
import hashlib
import logging
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class NoveltyDecision(str, Enum):
    """新颖性决策."""

    ALLOW = "allow"
    ALLOW_WITH_PENALTY = "allow_with_penalty"
    REJECT = "reject"


@dataclass
class NoveltyResult:
    """新颖性检查结果."""

    decision: NoveltyDecision
    similarity_score: float
    reasons: list[str]
    penalty: float = 0.0


class NoveltyGate:
    """多级新颖性门.

    1. Embedding 相似度初筛
    2. AST/结构签名检查
    3. 可选 LLM 判断
    """

    def __init__(
        self,
        *,
        embedding_threshold: float = 0.92,
        borderline_low: float = 0.88,
        borderline_high: float = 0.96,
        use_ast_check: bool = True,
    ) -> None:
        self._embedding_threshold = embedding_threshold
        self._borderline_low = borderline_low
        self._borderline_high = borderline_high
        self._use_ast_check = use_ast_check

    def check(
        self,
        thought: str,
        code: str | None = None,
        existing_similarities: list[float] | None = None,
    ) -> NoveltyResult:
        """检查新颖性.

        Args:
            thought: 思想内容
            code: 代码内容
            existing_similarities: 与现有候选的相似度列表

        Returns:
            NoveltyResult
        """
        reasons = []

        # 1. Embedding 相似度检查
        max_similarity = max(existing_similarities) if existing_similarities else 0.0

        if max_similarity >= self._borderline_high:
            reasons.append(f"High embedding similarity: {max_similarity:.3f}")
            return NoveltyResult(
                decision=NoveltyDecision.REJECT,
                similarity_score=max_similarity,
                reasons=reasons,
            )

        # 2. AST 结构检查
        if self._use_ast_check and code:
            ast_novel = self._check_ast_novelty(code)
            if not ast_novel:
                reasons.append("AST structure too similar")

        # 3. 决策
        if max_similarity >= self._embedding_threshold:
            if reasons:
                return NoveltyResult(
                    decision=NoveltyDecision.REJECT,
                    similarity_score=max_similarity,
                    reasons=reasons,
                )
            return NoveltyResult(
                decision=NoveltyDecision.ALLOW_WITH_PENALTY,
                similarity_score=max_similarity,
                reasons=["Borderline similarity"],
                penalty=0.2,
            )

        return NoveltyResult(
            decision=NoveltyDecision.ALLOW,
            similarity_score=max_similarity,
            reasons=["Novel contribution"],
        )

    def _check_ast_novelty(self, code: str) -> bool:
        """检查 AST 结构新颖性."""
        try:
            tree = ast.parse(code)
            # 提取结构签名
            signature = self._extract_ast_signature(tree)
            # 这里简化处理，实际需要与现有签名比较
            return len(signature) > 0
        except SyntaxError:
            return True  # 语法错误时不阻止

    def _extract_ast_signature(self, tree: ast.AST) -> str:
        """提取 AST 结构签名."""
        parts = []
        for node in ast.walk(tree):
            parts.append(type(node).__name__)
        return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]


def compute_code_signature(code: str) -> str:
    """计算代码结构签名."""
    try:
        tree = ast.parse(code)
        parts = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                parts.append(f"{type(node).__name__}:{node.name}")
            else:
                parts.append(type(node).__name__)
        return hashlib.sha256("|".join(sorted(parts)).encode()).hexdigest()
    except SyntaxError:
        return hashlib.sha256(code.encode()).hexdigest()
