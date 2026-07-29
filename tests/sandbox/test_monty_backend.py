"""MontyBackend 单元测试.

需要 pip install omnievolve[monty] 并安装 pydantic-monty。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from omnievolve.sandbox.base import (
    CandidateArtifact,
    EvaluationPlan,
    SandboxPolicy,
)
from omnievolve.sandbox.monty_backend import MontyBackend, is_monty_available

pytestmark = pytest.mark.integration

pytest.importorskip("pydantic_monty", reason="pydantic-monty not installed")


@pytest.fixture
def monty_backend(tmp_path: Path):
    """创建 Monty 后端."""
    return MontyBackend(work_dir=tmp_path / "monty_sandbox")


@pytest.fixture
def default_policy():
    """默认安全策略."""
    return SandboxPolicy(
        timeout_sec=5.0,
        mem_limit_mb=128,
        cpu_limit=1.0,
    )


class FakeArtifactStore:
    """模拟 ArtifactStore."""

    def __init__(self, code: str = ""):
        self._code = code.encode("utf-8")

    def load(self, _hash: str) -> bytes:
        return self._code


class TestMontyHealthcheck:
    def test_healthcheck_healthy(self, monty_backend):
        health = monty_backend.healthcheck()
        assert health["status"] == "healthy"
        assert health["monty_available"] is True

    def test_is_monty_available(self):
        assert is_monty_available() is True


class TestMontyExecute:
    def test_execute_simple_expression(self, monty_backend, default_policy):
        """执行简单 Python 表达式."""
        monty_backend._artifact_store = FakeArtifactStore("print(1 + 2)")  # noqa: SLF001

        plan = EvaluationPlan(commands=[])
        result = monty_backend.execute(
            plan,
            CandidateArtifact("test", "h", None, "python"),
            default_policy,
        )

        assert result.return_codes == [0]
        assert "3" in result.stdout
        assert not result.timed_out

    def test_execute_variable_state(self, monty_backend, default_policy):
        """代码内状态保持."""
        monty_backend._artifact_store = FakeArtifactStore(  # noqa: SLF001
            "x = 42\nprint(x * 2)"
        )

        plan = EvaluationPlan(commands=[])
        result = monty_backend.execute(
            plan,
            CandidateArtifact("test", "h", None, "python"),
            default_policy,
        )

        assert result.return_codes == [0]
        assert "84" in result.stdout

    def test_execute_syntax_error(self, monty_backend, default_policy):
        """语法错误."""
        monty_backend._artifact_store = FakeArtifactStore("print(1 / 0")  # noqa: SLF001

        plan = EvaluationPlan(commands=[])
        result = monty_backend.execute(
            plan,
            CandidateArtifact("test", "h", None, "python"),
            default_policy,
        )

        assert result.return_codes == [1]
        assert not result.timed_out

    def test_execute_runtime_error(self, monty_backend, default_policy):
        """运行时错误."""
        monty_backend._artifact_store = FakeArtifactStore(  # noqa: SLF001
            "raise ValueError('test error')"
        )

        plan = EvaluationPlan(commands=[])
        result = monty_backend.execute(
            plan,
            CandidateArtifact("test", "h", None, "python"),
            default_policy,
        )

        assert result.return_codes == [1]

    def test_timeout_enforced(self, monty_backend):
        """超时限制生效."""
        monty_backend._artifact_store = FakeArtifactStore(  # noqa: SLF001
            "while True: pass"
        )

        policy = SandboxPolicy(timeout_sec=0.5, mem_limit_mb=64)
        plan = EvaluationPlan(commands=[])
        result = monty_backend.execute(
            plan,
            CandidateArtifact("test", "h", None, "python"),
            policy,
        )

        assert result.timed_out or result.return_codes != [0]

    def test_memory_limit_enforced(self, monty_backend):
        """内存限制生效."""
        monty_backend._artifact_store = FakeArtifactStore(  # noqa: SLF001
            "data = [0] * (50 * 1024 * 1024)"  # 50M ints ≈ 400 MB
        )

        policy = SandboxPolicy(timeout_sec=10.0, mem_limit_mb=64)
        plan = EvaluationPlan(commands=[])
        result = monty_backend.execute(
            plan,
            CandidateArtifact("test", "h", None, "python"),
            policy,
        )

        assert result.return_codes != [0] or result.policy_violation is not None

    def test_no_filesystem_access(self, monty_backend, default_policy):
        """不能访问宿主文件系统."""
        monty_backend._artifact_store = FakeArtifactStore(  # noqa: SLF001
            "open('/etc/passwd').read()"
        )

        plan = EvaluationPlan(commands=[])
        result = monty_backend.execute(
            plan,
            CandidateArtifact("test", "h", None, "python"),
            default_policy,
        )

        assert result.return_codes != [0]

    def test_stdout_capture(self, monty_backend, default_policy):
        """stdout 捕获正常."""
        monty_backend._artifact_store = FakeArtifactStore(  # noqa: SLF001
            "print('hello'); print('world')"
        )

        plan = EvaluationPlan(commands=[])
        result = monty_backend.execute(
            plan,
            CandidateArtifact("test", "h", None, "python"),
            default_policy,
        )

        assert result.return_codes == [0]
        assert "hello" in result.stdout
        assert "world" in result.stdout


class TestMontyEnvironmentVersion:
    def test_version_id_stable(self, tmp_path):
        """相同 Monty runtime 生成相同的 environment_version_id."""
        b1 = MontyBackend(work_dir=tmp_path / "a")
        b2 = MontyBackend(work_dir=tmp_path / "b")
        assert b1.environment_version_id == b2.environment_version_id

    def test_version_id_format(self, monty_backend):
        """version_id 格式包含 Monty runtime 版本."""
        vid = monty_backend.environment_version_id
        assert vid.startswith("monty-")
        assert len(vid) == 14  # "monty-" + 8 hex chars
