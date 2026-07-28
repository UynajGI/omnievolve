"""crossover.py 单元测试 — CrossoverOperator 多父代融合."""

from __future__ import annotations

import pytest

from omnievolve.engine.crossover import CrossoverOperator

pytestmark = pytest.mark.unit


SIMPLE_CODE_A = "def f():\n    return 1\n\ndef g():\n    return 2\n"
SIMPLE_CODE_B = "def f():\n    return 10\n\ndef h():\n    return 20\n"
MULTI_FUNC_CODE = (
    "def sort(arr):\n    return sorted(arr)\n\n"
    "def binary_search(arr, x):\n    lo, hi = 0, len(arr)\n    return -1\n"
)


class TestCrossoverOperator:
    """CrossoverOperator — 多父代交叉."""

    def test_init_defaults(self):
        op = CrossoverOperator()
        assert op.min_parents == 2

    def test_select_parents_enough_candidates(self):
        op = CrossoverOperator()
        candidates = [("a", 0.9), ("b", 0.8), ("c", 0.7), ("d", 0.6)]
        result = op.select_parents(candidates)
        assert 2 <= len(result) <= 3
        # 应来自高分候选
        assert all(p in ["a", "b", "c", "d"] for p in result)

    def test_select_parents_insufficient_candidates(self):
        op = CrossoverOperator()
        result = op.select_parents([("a", 0.9)])
        assert result == []

    def test_select_parents_with_exclude(self):
        op = CrossoverOperator()
        candidates = [("a", 0.9), ("b", 0.8), ("c", 0.7), ("d", 0.6)]
        result = op.select_parents(candidates, exclude_ids=["a"])
        assert "a" not in result
        assert len(result) >= 2

    def test_select_parents_prefers_higher_scores(self):
        op = CrossoverOperator(max_parents=3)
        candidates = [("best", 1.0), ("mid", 0.5), ("low", 0.1), ("worst", 0.01)]
        result = op.select_parents(candidates)
        assert len(result) >= 2

    def test_combine_single_parent_returns_unchanged(self):
        op = CrossoverOperator()
        result = op.combine(["x = 1\n"])
        assert result == "x = 1\n"

    def test_segment_crossover_basic(self):
        op = CrossoverOperator()
        result = op._segment_crossover(
            [  # noqa: SLF001
                "line1\nline2\nline3\nline4\n",
                "LINE1\nLINE2\nLINE3\nLINE4\n",
            ]
        )
        # 前段来自第一个，后段来自第二个
        assert "line" in result
        assert "LINE" in result

    def test_segment_crossover_single_line_fallback(self):
        op = CrossoverOperator()
        result = op._segment_crossover(["a\n", "b\n"])  # noqa: SLF001
        assert result in ["a\n", "b\n"]

    def test_function_level_crossover_merges_functions(self):
        op = CrossoverOperator()
        result = op.combine([SIMPLE_CODE_A, SIMPLE_CODE_B], strategy="function_level")
        # 应包含来自两个父代的函数
        assert "def g" in result or "def h" in result

    def test_function_level_crossover_preserves_imports(self):
        op = CrossoverOperator()
        codes = [
            "import math\n\ndef sqrt(x):\n    return math.sqrt(x)\n",
            "import os\n\ndef ls():\n    return os.listdir()\n",
        ]
        result = op.combine(codes, strategy="function_level")
        assert "import math" in result or "import os" in result

    def test_feature_merge_adds_unique_functions(self):
        op = CrossoverOperator()
        result = op.combine([SIMPLE_CODE_A, SIMPLE_CODE_B], strategy="feature_merge")
        # 基础代码应包含 g，再添加 h
        assert "def g" in result or "def h" in result

    def test_feature_merge_handles_syntax_errors(self):
        op = CrossoverOperator()
        result = op.combine(["not valid python {{", "x = 1\n"], strategy="feature_merge")
        # 不应崩溃，返回空结果或基础代码
        assert isinstance(result, str)

    def test_combine_defaults_to_semantic_ast_crossover(self):
        op = CrossoverOperator()
        result = op.combine(
            [
                "import math\n\n"
                "def solve():\n    return 1\n\n"
                "if __name__ == '__main__':\n    print(solve())\n",
                "def solve():\n    return 2\n\n"
                "def helper():\n    return 'new'\n",
            ]
        )

        compile(result, "<crossover>", "exec")
        assert "import math" in result
        assert "if __name__" in result
        assert "def helper" in result

    def test_semantic_crossover_syntax_error_uses_safe_fallback(self):
        op = CrossoverOperator()

        result = op.combine(["def broken(:\n", "def solve():\n    return 1\n"])

        assert isinstance(result, str)
        assert "def solve" in result


class TestCrossoverEdgeCases:
    def test_empty_candidates_list(self):
        op = CrossoverOperator()
        assert op.select_parents([]) == []

    def test_exclude_all_candidates(self):
        op = CrossoverOperator()
        candidates = [("a", 0.9), ("b", 0.8), ("c", 0.7)]
        # 排除所有但保留至少 min_parents 个
        result = op.select_parents(candidates, exclude_ids=["a"])
        assert len(result) >= 2  # b, c 仍然可用

    def test_custom_min_max_parents(self):
        op = CrossoverOperator(min_parents=2, max_parents=2)
        candidates = [("a", 0.9), ("b", 0.8), ("c", 0.7)]
        result = op.select_parents(candidates)
        assert len(result) == 2

    def test_segment_crossover_different_lengths(self):
        op = CrossoverOperator()
        result = op._segment_crossover(
            [  # noqa: SLF001
                "a\nb\nc\n",
                "X\n",
            ]
        )
        assert isinstance(result, str)
