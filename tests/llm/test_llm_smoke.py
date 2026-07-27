"""Tier 2 LLM 烟雾测试 — 2-3代真实进化，验证管线连通性.

分层测试策略（见 feedback/layered-llm-testing）：
  Tier 1: FakeLLM 单元测试 — 每次 CI 都跑（make test）
  Tier 2: 真实 LLM 短跑 2-3 代 — 偶尔手动触发（make test-llm）
  Tier 3: 30+ 代完整进化 — milestone 手动执行（不进 CI）

经济性：Tier 2 每次约 8-24 次 API 调用
（2-3 代 × population_size 2 × Director/Coder），
远低于 Tier 3 的数百次调用。

运行方式:
  # 需要设置 LLM API key
  export DEEPSEEK_API_KEY="sk-..."
  export OMNIEVOLVE_LLM_MODEL="openai/custom-model"
  export OMNIEVOLVE_LLM_API_BASE="https://example.com/v1"
  make test-llm
  # 或手动：
  .venv/bin/python -m pytest tests/llm/test_llm_smoke.py -v -m llm_smoke
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

# 与 CLI 保持相同优先级；真实凭据只放在 gitignored .local.env。
load_dotenv(".env", override=False)
load_dotenv(".local.env", override=True)

# 自动跳过条件：无 API key 或无 litellm
pytestmark = [
    pytest.mark.llm,
    pytest.mark.llm_smoke,
    pytest.mark.slow,
]

_API_KEYS = ["DEEPSEEK_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"]


def _has_api_key() -> bool:
    return any(os.environ.get(k) for k in _API_KEYS)


def _has_litellm() -> bool:
    try:
        import litellm  # noqa: F401

        return True
    except ImportError:
        return False


# 运行时跳过（而非 collection 跳过，便于查看测试存在）
@pytest.fixture(autouse=True)
def _skip_if_no_api():
    if not _has_api_key():
        pytest.skip(f"No API key found (checked: {', '.join(_API_KEYS)})")
    if not _has_litellm():
        pytest.skip("litellm not installed (pip install litellm)")


def _get_model() -> str:
    """选择可用的模型."""
    if model := os.environ.get("OMNIEVOLVE_LLM_MODEL"):
        return model
    if os.environ.get("DEEPSEEK_API_KEY"):
        return "deepseek/deepseek-chat"
    if os.environ.get("OPENAI_API_KEY"):
        return "gpt-4o-mini"
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "claude-3-haiku-20240307"
    return "deepseek/deepseek-chat"


def _get_api_base() -> str | None:
    """获取 OpenAI 兼容 API 地址（如果配置）."""
    return os.environ.get("OMNIEVOLVE_LLM_API_BASE") or os.environ.get("OPENAI_BASE_URL")


def _get_max_tokens() -> int:
    """限制 smoke 测试的单次输出预算."""
    return int(os.environ.get("OMNIEVOLVE_LLM_MAX_TOKENS", "4096"))


class TestLLMSmoke:
    """2-3代真实进化 — 验证 Fast Loop 11步全流程连通."""

    def test_heilbronn_2gen(self, tmp_path):
        """Heilbronn 三角问题 — 2代 × 2候选 = 4个 LLM 调用."""
        from examples.heilbronn.evaluator import HeilbronnEvaluator
        from omnievolve.agents.llm_gateway import LLMGateway
        from omnievolve.engine.evolution_engine import (
            EvolutionConfig,
            EvolutionEngine,
        )
        from omnievolve.sandbox.subprocess_backend import TrustedSubprocessBackend
        from omnievolve.storage.artifact_store import ArtifactStore
        from omnievolve.storage.db import Database
        from omnievolve.storage.migrations import initialize_database
        from omnievolve.storage.repositories.experiment_repo import ExperimentRepository

        db = Database(tmp_path / "llm_smoke.db")
        initialize_database(db)
        artifact_store = ArtifactStore(tmp_path / "artifacts", db)
        sandbox = TrustedSubprocessBackend(
            work_dir=tmp_path / "sandbox",
            artifact_store=artifact_store,
            trusted=True,
        )
        experiment = ExperimentRepository(db).create(
            task_id="heilbronn",
            task_name="heilbronn",
            config_snapshot={"test": "llm_smoke"},
        )
        model = _get_model()

        gateway = LLMGateway(
            default_model=model,
            api_base=_get_api_base(),
            default_max_tokens=_get_max_tokens(),
            max_retries=2,
            retry_backoff_base=1.0,
        )

        engine = EvolutionEngine(
            db=db,
            artifact_store=artifact_store,
            task_evaluator=HeilbronnEvaluator(),
            sandbox=sandbox,
            llm=gateway,
            config=EvolutionConfig(
                max_generations=2,
                population_size=2,
                island_count=1,
                crossover_rate=0.0,  # 减少调用
                self_evolve_enabled=False,
            ),
            experiment_id=experiment.id,
            evaluator_version_id=HeilbronnEvaluator.version_id,
            environment_version_id=sandbox.environment_version_id,
        )

        initial_code = Path("examples/heilbronn/initial_code.py").read_text(encoding="utf-8")
        result = engine.run(initial_code, "heilbronn")

        # 基本断言：管线完成，有候选，有分数
        assert result is not None
        assert result.total_candidates >= 2
        assert result.best_score > 0
        # 至少有一个候选是通过 LLM 生成的（非初始）
        assert result.total_candidates > 1

    def test_router_selects_model(self):
        """验证 ModelRouter 在真实 LLM 环境下工作."""
        from omnievolve.agents.llm_gateway import LLMGateway

        model = _get_model()
        gateway = LLMGateway(
            default_model=model,
            api_base=_get_api_base(),
            default_max_tokens=_get_max_tokens(),
        )

        # 简单验证：gateway 能发起调用并返回结果
        response = gateway.chat(
            [{"role": "user", "content": "Return the number 42. Nothing else."}],
            model=model,
            temperature=0.0,
            max_tokens=64,
        )

        assert response is not None
        assert response.model == model
        assert response.content
        assert len(response.content) > 0
