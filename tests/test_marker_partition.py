"""pytest marker 集合审计（required lanes 互斥）.

CI 与 lefthook 消费同一组 marker 表达式（见 pyproject.toml 集合约定）：
- fast        = not llm and not llm_smoke and not slow and not e2e and not benchmark
- integration = (slow or e2e) and not llm and not llm_smoke and not benchmark
- llm         = llm or llm_smoke
- benchmark   = benchmark

审计：各集合互斥，且覆盖全部测试节点，防止 marker 漂移导致
CI 重复运行 / 本地 pre-push 与 CI 语义不一致。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

FAST = "not llm and not llm_smoke and not slow and not e2e and not benchmark"
INTEGRATION = "(slow or e2e) and not llm and not llm_smoke and not benchmark"
LLM = "llm or llm_smoke"
BENCHMARK = "benchmark"


def _collect(marker_expr: str) -> set[str]:
    """用 pytest --collect-only 收集匹配表达式的节点（marker 权威来源）."""
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "-m",
            marker_expr,
            "tests/",
        ],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    return {
        line.strip() for line in result.stdout.splitlines() if line.strip().startswith("tests/")
    }


def test_lanes_are_disjoint():
    fast = _collect(FAST)
    integration = _collect(INTEGRATION)
    llm = _collect(LLM)
    benchmark = _collect(BENCHMARK)
    assert fast, "fast 集合为空"
    assert integration, "integration 集合为空"
    assert fast.isdisjoint(integration), (
        f"fast 与 integration 重叠: {sorted(fast & integration)[:10]}"
    )
    assert fast.isdisjoint(benchmark), "fast 与 benchmark 重叠"
    assert integration.isdisjoint(benchmark), "integration 与 benchmark 重叠"
    assert llm.isdisjoint(fast | integration | benchmark), "llm 与 required lane 重叠"


def test_lanes_cover_suite():
    """required lane 覆盖全部测试节点（防 marker 漂移）."""
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "tests/"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    total = {
        line.strip() for line in result.stdout.splitlines() if line.strip().startswith("tests/")
    }
    covered = _collect(FAST) | _collect(INTEGRATION) | _collect(LLM) | _collect(BENCHMARK)
    uncovered = total - covered
    assert not uncovered, f"未归入任何 required lane 的节点: {sorted(uncovered)[:10]}"
