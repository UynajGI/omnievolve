.PHONY: test test-unit test-llm test-slow test-cov lint type-check clean

# ─── 分层测试（见 feedback/layered-llm-testing）──────────────────
# Tier 1: 快速单元测试（FakeLLM）— 每次 commit/CI 都跑
# Tier 2: LLM 烟雾测试（2-3代真实进化）— 偶尔手动触发
# Tier 3: 完整进化（30+代）— milestone 手动执行，不进 CI

PYTHON ?= .venv/bin/python
PYTEST ?= .venv/bin/python -m pytest

# Tier 1 — 快速单元测试（默认）
test: test-unit

test-unit:
	$(PYTEST) -q -m "not slow and not llm and not llm_smoke" --tb=short

# Tier 1 + 覆盖率
test-cov:
	$(PYTEST) -q -m "not slow and not llm and not llm_smoke" --cov=omnievolve --cov-report=term --tb=short

# Tier 2 — LLM 烟雾测试（需要 API key，约 4-12 次 API 调用）
test-llm:
	$(PYTEST) tests/llm/ -v -m "llm_smoke" --tb=short

# 慢速/集成测试（Docker, soak 等）
test-slow:
	$(PYTEST) -q -m "slow" --tb=short

# 全量（不含 LLM）
test-all:
	$(PYTEST) -q -m "not llm and not llm_smoke" --tb=short

# ─── 代码质量 ─────────────────────────────────────────────────────

lint:
	.venv/bin/ruff check src/omnievolve/ tests/

type-check:
	$(PYTHON) -m mypy src/omnievolve/ --ignore-missing-imports

# ─── 清理 ────────────────────────────────────────────────────────

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache .hypothesis
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
