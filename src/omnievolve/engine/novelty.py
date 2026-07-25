"""多级 NoveltyGate.

S7-05: 实现 Embedding 新颖性预筛
S7-06: 实现 AST/结构签名
S7-08: 实现多级 NoveltyGate 决策器
"""

from __future__ import annotations

import ast
import hashlib
import logging
from collections import OrderedDict
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
    3. Epiplexity 可学习新奇性预筛（任务无关）
    4. 可选行为签名
    5. 可选 LLM 判断（borderline 时触发）
    """

    def __init__(
        self,
        *,
        embedding_threshold: float = 0.92,
        borderline_low: float = 0.88,
        borderline_high: float = 0.96,
        use_ast_check: bool = True,
        use_epiplexity: bool = True,
        epiplexity_min: float = 0.1,
        llm_judge: LLMNoveltyJudge | None = None,
        max_cached_signatures: int = 200,
    ) -> None:
        self._embedding_threshold = embedding_threshold
        self._borderline_low = borderline_low
        self._borderline_high = borderline_high
        self._use_ast_check = use_ast_check
        self._use_epiplexity = use_epiplexity
        self._epiplexity_min = epiplexity_min
        self._llm_judge = llm_judge
        # AST 签名缓存（LRU 淘汰，最近 N 个候选的结构签名）
        self._recent_signatures: OrderedDict[str, None] = OrderedDict()
        self._max_cached_signatures = max_cached_signatures

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
                reasons.append("AST structure identical to recent candidate")

        # 2.5 Epiplexity 可学习新奇性预筛（任务无关）
        if self._use_epiplexity and code:
            epi_score = self._check_epiplexity(code)
            if epi_score < self._epiplexity_min:
                reasons.append(
                    f"Low epiplexity ({epi_score:.3f}): code is too trivial or too random"
                )
                return NoveltyResult(
                    decision=NoveltyDecision.REJECT,
                    similarity_score=max_similarity,
                    reasons=reasons,
                )

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

        # 3.5 borderline 区域：可选 LLM 判断
        if (
            self._llm_judge is not None
            and self._borderline_low <= max_similarity < self._embedding_threshold
        ):
            try:
                llm_decision = self._llm_judge.judge(thought, code, max_similarity)
                if llm_decision == "reject":
                    return NoveltyResult(
                        decision=NoveltyDecision.REJECT,
                        similarity_score=max_similarity,
                        reasons=["LLM novelty judge: reject"],
                    )
                elif llm_decision == "allow_with_penalty":
                    return NoveltyResult(
                        decision=NoveltyDecision.ALLOW_WITH_PENALTY,
                        similarity_score=max_similarity,
                        reasons=["LLM novelty judge: borderline"],
                        penalty=0.15,
                    )
            except Exception:
                logger.debug("LLM novelty judge failed, falling through", exc_info=True)

        return NoveltyResult(
            decision=NoveltyDecision.ALLOW,
            similarity_score=max_similarity,
            reasons=["Novel contribution"],
        )

    def _check_ast_novelty(self, code: str) -> bool:
        """检查 AST 结构新颖性（与最近候选的签名比较）."""
        try:
            tree = ast.parse(code)
            signature = self._extract_ast_signature(tree)
            if not signature:
                return True
            # 与现有签名比较：完全相同则不新颖
            if signature in self._recent_signatures:
                return False
            # 加入缓存（LRU 淘汰）
            self._recent_signatures[signature] = None
            if len(self._recent_signatures) > self._max_cached_signatures:
                self._recent_signatures.popitem(last=False)
            return True
        except SyntaxError:
            return True  # 语法错误时不阻止

    def _extract_ast_signature(self, tree: ast.AST) -> str:
        """提取 AST 结构签名."""
        parts = []
        for node in ast.walk(tree):
            parts.append(type(node).__name__)
        return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]

    def _check_epiplexity(self, code: str) -> float:
        """计算代码的可学习新奇性分数.

        基于 LEARNABLE_NOVELTY (2607.18433):
        - 太简单（平凡）→ 0
        - 太复杂（随机）→ 0
        - 临界复杂度 → 最大值
        """
        from omnievolve.engine.epiplexity import EpiplexityEstimator

        if not hasattr(self, "_epiplexity_estimator"):
            self._epiplexity_estimator = EpiplexityEstimator()
        return self._epiplexity_estimator.score(code)


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


class LLMNoveltyJudge:
    """LLM 辅助新颖性判断器.

    S7-09: 在 borderline 区域（borderline_low ~ borderline_high）
    调用 LLM 做最终新颖性判断，而非单一 Embedding 一票否决。

    LLM 只需返回 allow / reject / allow_with_penalty 之一，
    判断基于机制标签、算法类型和解决路径的差异。
    """

    JUDGE_PROMPT = """You are a novelty judge for an evolutionary code optimization system.

Given an improvement thought and its embedding similarity score, determine if it
represents a genuinely novel contribution or a minor rephrasing of existing work.

Focus on mechanism differences, not surface text similarity.

Thought: {thought}
Similarity score: {similarity:.3f}
Code preview: {code_preview}

Respond with exactly one word: allow, reject, or allow_with_penalty"""

    def __init__(self, llm: object | None = None) -> None:
        self._llm = llm

    def judge(
        self,
        thought: str,
        code: str | None,
        similarity: float,
    ) -> str:
        """判断新颖性.

        Returns:
            'allow' / 'reject' / 'allow_with_penalty'
        """
        if self._llm is None:
            # 无 LLM 时默认放行 borderline
            return "allow_with_penalty"

        prompt = self.JUDGE_PROMPT.format(
            thought=thought[:500],
            similarity=similarity,
            code_preview=(code or "")[:500],
        )

        try:
            response = self._llm.chat(  # type: ignore[attr-defined]
                [{"role": "user", "content": prompt}],
                agent_role="meta",
            )
            decision = (response.content or "").strip().lower()
            for valid in ("allow", "reject", "allow_with_penalty"):
                if valid in decision:
                    return valid
            return "allow_with_penalty"
        except Exception:
            logger.debug("LLM novelty judge failed", exc_info=True)
            return "allow_with_penalty"
