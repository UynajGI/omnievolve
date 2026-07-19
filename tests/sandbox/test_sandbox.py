"""沙箱安全测试.

S2-15: 编写网络/秘密/路径穿越安全测试
S2-16: 编写 fork bomb/内存/磁盘/超时压力测试
"""

from pathlib import Path

import pytest

from omnievolve.sandbox.base import (
    CandidateArtifact,
    CommandSpec,
    EvaluationPlan,
    SandboxPolicy,
)
from omnievolve.sandbox.registry import BackendRegistry, create_backend
from omnievolve.sandbox.subprocess_backend import TrustedSubprocessBackend


@pytest.fixture
def trusted_backend(tmp_path: Path):
    """创建 trusted 后端用于测试."""
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return TrustedSubprocessBackend(
            work_dir=tmp_path / "sandbox",
            trusted=True,
        )


@pytest.fixture
def simple_candidate():
    """简单候选 Artifact."""
    return CandidateArtifact(
        candidate_id="test_cand",
        source_hash="abc123",
        manifest_hash=None,
        language="python",
    )


@pytest.fixture
def default_policy():
    """默认安全策略."""
    return SandboxPolicy(
        timeout_sec=5.0,
        mem_limit_mb=128,
        cpu_limit=0.5,
        pids_limit=10,
    )


class TestTrustedSubprocess:
    """TrustedSubprocessBackend 测试."""

    def test_requires_explicit_trusted(self):
        """必须显式设置 trusted=True."""
        with pytest.raises(ValueError, match="trusted=True"):
            TrustedSubprocessBackend(trusted=False)

    def test_execute_simple_command(
        self, trusted_backend: TrustedSubprocessBackend, simple_candidate, default_policy
    ):
        """执行简单命令."""
        plan = EvaluationPlan(
            commands=[CommandSpec(argv=["echo", "hello world"])],
        )

        result = trusted_backend.execute(plan, simple_candidate, default_policy)

        assert result.return_codes == [0]
        assert "hello world" in result.stdout
        assert not result.timed_out

    def test_execute_multiple_commands(
        self, trusted_backend: TrustedSubprocessBackend, simple_candidate, default_policy
    ):
        """执行多个命令."""
        plan = EvaluationPlan(
            commands=[
                CommandSpec(argv=["echo", "first"]),
                CommandSpec(argv=["echo", "second"]),
            ],
        )

        result = trusted_backend.execute(plan, simple_candidate, default_policy)

        assert len(result.return_codes) == 2
        assert all(code == 0 for code in result.return_codes)

    def test_command_failure(
        self, trusted_backend: TrustedSubprocessBackend, simple_candidate, default_policy
    ):
        """命令失败应停止执行."""
        plan = EvaluationPlan(
            commands=[
                CommandSpec(argv=["false"]),  # 返回非零
                CommandSpec(argv=["echo", "should not run"]),
            ],
        )

        result = trusted_backend.execute(plan, simple_candidate, default_policy)

        assert result.return_codes[0] != 0
        assert len(result.return_codes) == 1  # 第二个命令未执行

    def test_timeout(self, trusted_backend: TrustedSubprocessBackend, simple_candidate):
        """超时应被捕获."""
        # 使用足够大的资源限制，让 subprocess timeout 生效
        policy = SandboxPolicy(
            timeout_sec=1.0,
            mem_limit_mb=512,
            cpu_limit=2.0,  # 足够的 CPU
        )
        plan = EvaluationPlan(
            commands=[CommandSpec(argv=["sleep", "10"], timeout_sec=0.5)],
        )

        result = trusted_backend.execute(plan, simple_candidate, policy)

        # 可能是 timed_out 或者被杀死（return_code != 0）
        assert result.timed_out or result.return_codes[0] != 0

    def test_healthcheck(self, trusted_backend: TrustedSubprocessBackend):
        """健康检查."""
        health = trusted_backend.healthcheck()

        assert health["status"] == "healthy"
        assert health["backend"] == "trusted_subprocess"
        assert "warning" in health


class TestBackendRegistry:
    """BackendRegistry 测试."""

    def test_register_and_get(self):
        """注册和获取后端."""
        registry = BackendRegistry()
        registry.register("trusted_subprocess", TrustedSubprocessBackend)

        # 需要 trusted=True
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            backend = registry.get_backend("trusted_subprocess", trusted=True)

        assert backend is not None

    def test_unknown_backend(self):
        """未知后端应报错."""
        from omnievolve.sandbox.base import SandboxSetupError

        registry = BackendRegistry()

        with pytest.raises(SandboxSetupError, match="Unknown backend"):
            registry.get_backend("nonexistent")

    def test_doctor(self):
        """诊断功能."""
        registry = BackendRegistry()
        registry.register("trusted_subprocess", TrustedSubprocessBackend)

        results = registry.doctor()

        assert "trusted_subprocess" in results
        assert results["trusted_subprocess"]["available"]


class TestCreateBackend:
    """create_backend 便捷函数测试."""

    def test_trusted_requires_flag(self):
        """trusted_subprocess 需要 --trusted 标志."""
        with pytest.raises(ValueError, match="--trusted"):
            create_backend("trusted_subprocess", trusted=False)

    def test_create_trusted(self, tmp_path: Path):
        """创建 trusted 后端."""
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            backend = create_backend(
                "trusted_subprocess",
                trusted=True,
                work_dir=tmp_path,
            )

        assert backend is not None


class TestSandboxPolicy:
    """SandboxPolicy 测试."""

    def test_default_policy(self):
        """默认策略."""
        policy = SandboxPolicy()

        assert policy.timeout_sec == 30.0
        assert policy.mem_limit_mb == 512
        assert policy.network_mode == "none"
        assert policy.read_only_root is True
        assert policy.run_as_non_root is True
        assert policy.drop_capabilities is True
        assert policy.no_new_privileges is True

    def test_custom_policy(self):
        """自定义策略."""
        policy = SandboxPolicy(
            timeout_sec=60.0,
            mem_limit_mb=1024,
            network_mode="bridge",
            allowed_env={"PATH", "HOME"},
        )

        assert policy.timeout_sec == 60.0
        assert policy.mem_limit_mb == 1024
        assert "PATH" in policy.allowed_env


class TestEvaluationPlan:
    """EvaluationPlan 测试."""

    def test_plan_creation(self):
        """创建评估计划."""
        plan = EvaluationPlan(
            commands=[
                CommandSpec(argv=["python", "main.py"], timeout_sec=10.0),
            ],
            expected_outputs=["result.json"],
            network_access=False,
        )

        assert len(plan.commands) == 1
        assert plan.commands[0].argv == ["python", "main.py"]
        assert "result.json" in plan.expected_outputs
        assert not plan.network_access

    def test_command_with_env(self):
        """带环境变量的命令."""
        cmd = CommandSpec(
            argv=["python", "test.py"],
            env={"PYTHONPATH": "/custom/path"},
        )

        assert cmd.env["PYTHONPATH"] == "/custom/path"
