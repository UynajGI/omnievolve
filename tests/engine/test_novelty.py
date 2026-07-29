"""novelty.py 单元测试 — NoveltyGate 多级新颖性门."""

from __future__ import annotations

import pytest

from omnievolve.engine.novelty import (
    NoveltyDecision,
    NoveltyGate,
    NoveltyResult,
    NoveltyStage,
)

pytestmark = pytest.mark.unit


class TestNoveltyDecision:
    def test_enum_values(self):
        assert NoveltyDecision.ALLOW.value == "allow"
        assert NoveltyDecision.REJECT.value == "reject"
        assert NoveltyDecision.ALLOW_WITH_PENALTY.value == "allow_with_penalty"


class TestNoveltyResult:
    def test_default_penalty_zero(self):
        result = NoveltyResult(
            decision=NoveltyDecision.ALLOW,
            similarity_score=0.5,
            reasons=[],
        )
        assert result.penalty == 0.0

    def test_penalty_set(self):
        result = NoveltyResult(
            decision=NoveltyDecision.ALLOW_WITH_PENALTY,
            similarity_score=0.93,
            reasons=["borderline"],
            penalty=0.3,
        )
        assert result.penalty == 0.3


class TestNoveltyGate:
    def test_idea_and_candidate_checks_have_distinct_audit_stages(self):
        gate = NoveltyGate()

        idea = gate.check_idea("replace comparison sorting with counting buckets")
        candidate = gate.check_candidate(
            "replace comparison sorting with counting buckets",
            "def solve(values):\n    return sorted(values)\n",
        )

        assert idea.stage == NoveltyStage.IDEA
        assert candidate.stage == NoveltyStage.CANDIDATE
        assert "idea_novelty_decision" in idea.to_metrics()
        assert "candidate_novelty_decision" in candidate.to_metrics()

    def test_final_candidate_exact_duplicate_is_rejected(self):
        code = "def solve(values):\n    return sorted(values)\n"
        gate = NoveltyGate()

        result = gate.check_candidate(
            "a superficially different idea",
            code,
            exact_reference_codes=[code],
        )

        assert result.stage == NoveltyStage.CANDIDATE
        assert result.decision == NoveltyDecision.REJECT
        assert result.similarity_score == 1.0
        assert result.reasons == ["Exact candidate code duplicate"]

    def test_penalty_reduces_only_novelty_objective(self):
        result = NoveltyResult(
            decision=NoveltyDecision.ALLOW_WITH_PENALTY,
            similarity_score=0.2,
            reasons=["borderline mechanism"],
            penalty=0.3,
            stage=NoveltyStage.CANDIDATE,
        )

        assert result.objective_score == pytest.approx(0.5)
        assert result.to_metrics()["candidate_novelty_penalty"] == 0.3

    def test_high_similarity_rejected(self):
        gate = NoveltyGate(embedding_threshold=0.92)
        result = gate.check("thought", existing_similarities=[0.97])
        assert result.decision == NoveltyDecision.REJECT
        assert result.similarity_score == 0.97

    def test_low_similarity_allowed(self):
        gate = NoveltyGate(embedding_threshold=0.92)
        result = gate.check("thought", existing_similarities=[0.5, 0.6])
        assert result.decision == NoveltyDecision.ALLOW

    def test_no_existing_similarities_allowed(self):
        gate = NoveltyGate()
        result = gate.check("thought")
        assert result.decision == NoveltyDecision.ALLOW

    def test_borderline_with_ast_novel(self):
        gate = NoveltyGate(embedding_threshold=0.92, borderline_high=0.96)
        result = gate.check(
            "use numpy vectorization",
            code="def solve():\n    import numpy as np\n    return np.sum(x)\n",
            existing_similarities=[0.93],
        )
        # 不应 REJECT（在 borderline 区域）
        assert result.decision != NoveltyDecision.REJECT

    def test_borderline_identical_code_rejected(self):
        code = "def f():\n    return 42\n"
        gate = NoveltyGate(embedding_threshold=0.92, borderline_high=0.99)
        # 高相似度应直接 REJECT
        result = gate.check("simple function", code=code, existing_similarities=[0.99])
        assert result.decision == NoveltyDecision.REJECT

    def test_ast_check_disabled(self):
        gate = NoveltyGate(embedding_threshold=0.92, use_ast_check=False)
        result = gate.check(
            "thought",
            code="def f():\n    pass\n",
            existing_similarities=[0.93],
        )
        # 禁用 AST 检查，borderline 但没有 reasons → ALLOW_WITH_PENALTY 或 ALLOW
        assert result.decision in (NoveltyDecision.ALLOW, NoveltyDecision.ALLOW_WITH_PENALTY)

    def test_similarities_argument_is_optional(self):
        gate = NoveltyGate()
        result = gate.check("thought", code="x = 1\n")
        assert result.decision == NoveltyDecision.ALLOW
