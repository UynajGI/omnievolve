"""Pytest shared fixtures.

提供跨测试文件的通用 fixture，减少重复定义。
"""

from __future__ import annotations

import pytest

from omnievolve.agents.llm_gateway import LLMResponse
from omnievolve.storage.artifact_store import ArtifactStore
from omnievolve.storage.db import create_memory_database
from omnievolve.storage.migrations import initialize_database
from omnievolve.storage.repositories.experiment_repo import ExperimentRepository


@pytest.fixture
def db():
    """创建内存数据库并运行迁移."""
    database = create_memory_database()
    initialize_database(database)
    yield database
    database.close()


@pytest.fixture
def artifact_store(db, tmp_path):
    """创建临时文件 ArtifactStore."""
    store = tmp_path / "artifacts"
    return ArtifactStore(store, db)


@pytest.fixture
def experiment(db):
    """创建测试实验."""
    repo = ExperimentRepository(db)
    exp = repo.create(task_id="test", task_name="test-task", config_snapshot={})
    return exp.id


# ── 共享 Fake LLM ──────────────────────────────────────────────────────
# 参考 ShinkaEvolve 测试模式: 统一 Fake 对象避免各测试文件重复定义


class FakeLLM:
    """按 agent_role 返回不同响应的 Fake LLM.

    测试文件可通过 monkeypatch / 子类化定制行为。
    """

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        experiment_id: str | None = None,
        agent_role: str = "unknown",
        prompt_version_id: str | None = None,
    ) -> LLMResponse:
        self.calls.append({"agent_role": agent_role, "model": model})

        if agent_role == "director":
            content = (
                '{"thought": "Try a faster algorithm", '
                '"rationale": "reduce complexity", '
                '"confidence": 0.8, '
                '"mechanism_tags": ["algo"]}'
            )
        elif agent_role == "coder":
            content = (
                '{"full_code": "x = 1\\nprint(x)", "diff": "rewrite", "explanation": "simpler"}'
            )
        else:
            content = '{"passed": true, "feedback": "ok"}'

        return LLMResponse(
            content=content,
            model=model or "fake",
            input_tokens=50,
            output_tokens=30,
            total_tokens=80,
            latency_ms=1.0,
        )


@pytest.fixture
def fake_llm():
    """共享 FakeLLM fixture — 所有 LLM 相关测试复用."""
    return FakeLLM()
