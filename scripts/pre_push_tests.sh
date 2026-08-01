#!/usr/bin/env bash
# pre-push fast 测试（与 CI fast 集合语义一致）。
# fast = not llm and not llm_smoke and not slow and not e2e and not benchmark
# （脚本内引号不经 lefthook 参数解析，避免 Windows 下 -m 表达式被截断）
set -euo pipefail

uv run --frozen pytest tests/ -q --tb=short \
  -m "not llm and not llm_smoke and not slow and not e2e and not benchmark"
