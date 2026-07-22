"""代码复杂度分析.

从 ShinkaEvolve complexity.py 移植。
Python 用 radon，其他语言用 generic 行数估计。
"""

from __future__ import annotations

import ast
import logging

logger = logging.getLogger(__name__)


def analyze_code_metrics(code: str, language: str = "python") -> dict:
    """分析代码复杂度.

    Returns:
        dict with keys: cyclomatic_complexity, halstead_volume,
        maintainability_index, nesting_depth, complexity_score (0-1)
    """
    if language == "python":
        return _analyze_python(code)
    return _analyze_generic(code)


def _analyze_python(code: str) -> dict:
    """Python 复杂度分析（使用 radon，懒加载）."""
    metrics = {
        "cyclomatic_complexity": 0,
        "halstead_volume": 0.0,
        "maintainability_index": 0.0,
        "nesting_depth": 0,
        "complexity_score": 0.0,
        "lines_of_code": len(code.splitlines()),
    }

    # 1. AST 嵌套深度（不需要 radon）
    try:
        tree = ast.parse(code)
        metrics["nesting_depth"] = _max_nesting_depth(tree)
    except SyntaxError:
        pass

    # 2. radon 分析（懒加载）
    try:
        from radon.complexity import cc_visit
        from radon.metrics import h_visit, mi_visit
        from radon.raw import analyze

        # Cyclomatic Complexity
        cc_results = cc_visit(code)
        if cc_results:
            metrics["cyclomatic_complexity"] = max(
                (c.complexity for c in cc_results), default=0
            )

        # Halstead
        h_results = h_visit(code)
        if h_results:
            metrics["halstead_volume"] = h_results.total.volume

        # Maintainability Index
        raw = analyze(code)
        metrics["maintainability_index"] = mi_visit(
            code, multi=True
        )
        metrics["lines_of_code"] = raw.lloc

    except ImportError:
        logger.debug("radon not installed, using generic complexity analysis")
        generic = _analyze_generic(code)
        metrics["cyclomatic_complexity"] = generic["cyclomatic_complexity"]
        metrics["halstead_volume"] = generic["halstead_volume"]
    except Exception:
        logger.debug("radon analysis failed", exc_info=True)

    # 归一化复杂度分数 (0-1)
    cc = metrics["cyclomatic_complexity"]
    nd = metrics["nesting_depth"]
    loc = metrics["lines_of_code"]
    # 复杂度分数 = 归一化的 CC × 嵌套因子
    metrics["complexity_score"] = min(1.0, (cc / 20.0) * 0.6 + (nd / 10.0) * 0.4)

    return metrics


def _analyze_generic(code: str) -> dict:
    """通用复杂度分析（行数 + 基础启发式）."""
    lines = code.splitlines()
    loc = len([l for l in lines if l.strip() and not l.strip().startswith("#")])

    # 估算 cyclomatic complexity
    control_keywords = (
        "if ", "elif ", "else:", "for ", "while ", "except ", "and ", "or "
    )
    cc = sum(
        sum(1 for kw in control_keywords if kw in line)
        for line in lines
    )

    # 估算嵌套深度
    max_indent = 0
    for line in lines:
        if line.strip():
            indent = len(line) - len(line.lstrip())
            max_indent = max(max_indent, indent // 4)

    return {
        "cyclomatic_complexity": cc,
        "halstead_volume": float(loc * (cc + 1)),
        "maintainability_index": max(0.0, 100.0 - cc * 2),
        "nesting_depth": max_indent,
        "complexity_score": min(1.0, (cc / 20.0) * 0.6 + (max_indent / 10.0) * 0.4),
        "lines_of_code": loc,
    }


def _max_nesting_depth(node: ast.AST, current_depth: int = 0) -> int:
    """递归计算 AST 最大嵌套深度."""
    max_depth = current_depth
    nesting_types = (
        ast.If, ast.For, ast.While, ast.With, ast.Try, ast.ExceptHandler,
        ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef,
    )
    for child in ast.iter_child_nodes(node):
        child_depth = current_depth + 1 if isinstance(child, nesting_types) else current_depth
        max_depth = max(max_depth, _max_nesting_depth(child, child_depth))
    return max_depth
