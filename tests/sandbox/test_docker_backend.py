"""DockerBackend 测试 — 配置构建单元测试 + 可选集成测试.

分层策略（见 feedback/layered-llm-testing）：
  - 配置构建逻辑：纯单元测试，始终运行
  - 真实 Docker 执行：@pytest.mark.slow，仅 Docker 可用时运行
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from omnievolve.sandbox.base import (
    CandidateArtifact,
    EvaluationPlan,
    SandboxPolicy,
    SandboxSetupError,
)
from omnievolve.sandbox.docker_backend import DockerBackend, is_docker_available


@pytest.fixture
def backend():
    return DockerBackend(image="python:3.12-slim")


@pytest.fixture
def simple_plan():
    return EvaluationPlan(
        commands=[],
    )


@pytest.fixture
def strict_policy():
    return SandboxPolicy(
        timeout_sec=10,
        mem_limit_mb=256,
        pids_limit=100,
        cpu_limit=1.0,
        read_only_root=True,
        network_mode="none",
        run_as_non_root=True,
        drop_capabilities=True,
        no_new_privileges=True,
        allowed_env={"PATH", "HOME"},
        tmpfs_mb=64,
    )


class TestEnvironmentVersionId:
    def test_unique_per_instance(self):
        b1 = DockerBackend()
        b2 = DockerBackend()
        assert b1.environment_version_id != b2.environment_version_id

    def test_prefix(self):
        b = DockerBackend()
        assert b.environment_version_id.startswith("docker-")


class TestGetClient:
    def test_raises_when_docker_not_installed(self, backend):
        """When docker package is missing, should raise SandboxSetupError."""
        with patch.dict("sys.modules", {"docker": None}):
            with pytest.raises(SandboxSetupError, match="not installed"):
                backend._get_client()

    def test_raises_when_daemon_unreachable(self, backend):
        """When docker daemon is unreachable, should raise SandboxSetupError."""
        mock_docker = MagicMock()
        mock_docker.from_env.side_effect = ConnectionError("daemon not running")
        with patch.dict("sys.modules", {"docker": mock_docker}):
            with pytest.raises(SandboxSetupError, match="Failed to connect"):
                backend._get_client()


class TestBuildContainerConfig:
    def test_basic_config(self, backend, strict_policy):
        from omnievolve.sandbox.base import CommandSpec

        plan = EvaluationPlan(
            commands=[CommandSpec(argv=["python", "main.py"])],
        )
        config = backend._build_container_config(plan, None, strict_policy)

        assert config["image"] == "python:3.12-slim"
        assert config["network_mode"] == "none"
        assert config["read_only"] is True
        assert config["user"] == "1000:1000"
        assert config["cap_drop"] == ["ALL"]
        assert config["security_opt"] == ["no-new-privileges:true"]
        assert config["working_dir"] == "/workspace"
        assert config["detach"] is True

    def test_memory_limit_format(self, backend, strict_policy):
        plan = EvaluationPlan(commands=[])
        config = backend._build_container_config(plan, None, strict_policy)
        assert config["mem_limit"] == "256m"

    def test_cpu_limit_in_nano(self, backend, strict_policy):
        plan = EvaluationPlan(commands=[])
        config = backend._build_container_config(plan, None, strict_policy)
        assert config["nano_cpus"] == int(1.0 * 1e9)

    def test_pids_limit(self, backend, strict_policy):
        plan = EvaluationPlan(commands=[])
        config = backend._build_container_config(plan, None, strict_policy)
        assert config["pids_limit"] == 100

    def test_tmpfs_when_read_only(self, backend, strict_policy):
        plan = EvaluationPlan(commands=[])
        config = backend._build_container_config(plan, None, strict_policy)
        assert "/tmp" in config["tmpfs"]
        assert "64m" in config["tmpfs"]["/tmp"]

    def test_no_tmpfs_when_writable(self, backend):
        policy = SandboxPolicy(
            timeout_sec=10,
            mem_limit_mb=256,
            pids_limit=100,
            cpu_limit=1.0,
            read_only_root=False,
            network_mode="none",
            run_as_non_root=False,
            drop_capabilities=False,
            no_new_privileges=False,
            allowed_env=set(),
            tmpfs_mb=64,
        )
        plan = EvaluationPlan(commands=[])
        config = backend._build_container_config(plan, None, policy)
        assert "tmpfs" not in config

    def test_env_whitelist_filtering(self, backend, strict_policy, monkeypatch):
        """Only allowed env vars are passed to container."""
        monkeypatch.setenv("PATH", "/usr/bin")
        monkeypatch.setenv("HOME", "/home/test")
        monkeypatch.setenv("SECRET_KEY", "leaked")  # should NOT appear

        plan = EvaluationPlan(commands=[])
        config = backend._build_container_config(plan, None, strict_policy)
        assert "PATH" in config["environment"]
        assert "HOME" in config["environment"]
        assert "SECRET_KEY" not in config["environment"]

    def test_network_none_by_default(self, backend, strict_policy):
        plan = EvaluationPlan(commands=[])
        config = backend._build_container_config(plan, None, strict_policy)
        assert config["network_mode"] == "none"

    def test_network_when_access_allowed(self, backend, strict_policy):
        from omnievolve.sandbox.base import CommandSpec

        plan = EvaluationPlan(
            commands=[CommandSpec(argv=["pip", "install", "pkg"])],
            network_access=True,
        )
        config = backend._build_container_config(plan, None, strict_policy)
        # When network_access is True, uses policy.network_mode
        assert config["network_mode"] == strict_policy.network_mode

    def test_none_values_removed(self, backend, strict_policy):
        plan = EvaluationPlan(commands=[])
        config = backend._build_container_config(plan, None, strict_policy)
        # No None values in config
        for v in config.values():
            assert v is not None


class TestBuildCommand:
    def test_single_command(self, backend):
        from omnievolve.sandbox.base import CommandSpec

        plan = EvaluationPlan(commands=[CommandSpec(argv=["python", "main.py"])])
        cmd = backend._build_command(plan)
        assert cmd[0] == "/bin/sh"
        assert cmd[1] == "-c"
        assert "python main.py" in cmd[2]

    def test_multiple_commands_chained(self, backend):
        from omnievolve.sandbox.base import CommandSpec

        plan = EvaluationPlan(
            commands=[
                CommandSpec(argv=["pip", "install", "numpy"]),
                CommandSpec(argv=["python", "main.py"]),
            ],
        )
        cmd = backend._build_command(plan)
        assert " && " in cmd[2]

    def test_no_commands_echo(self, backend):
        plan = EvaluationPlan(commands=[])
        cmd = backend._build_command(plan)
        assert cmd == ["echo", "No commands specified"]


class TestGetLogs:
    def test_normal_output(self, backend):
        container = MagicMock()
        container.logs.return_value = b"hello world"
        result = backend._get_logs(container, stdout=True)
        assert result == "hello world"

    def test_truncation(self, backend):
        """Output exceeding MAX_OUTPUT_BYTES is truncated."""
        from omnievolve.sandbox.docker_backend import MAX_OUTPUT_BYTES

        container = MagicMock()
        container.logs.return_value = b"x" * (MAX_OUTPUT_BYTES + 1000)
        result = backend._get_logs(container)
        assert len(result) < MAX_OUTPUT_BYTES + 100
        assert "TRUNCATED" in result

    def test_decode_errors_replaced(self, backend):
        container = MagicMock()
        container.logs.return_value = b"\xff\xfe invalid utf8"
        result = backend._get_logs(container)
        assert isinstance(result, str)

    def test_logs_failure_returns_empty(self, backend):
        container = MagicMock()
        container.logs.side_effect = Exception("logs unavailable")
        result = backend._get_logs(container)
        assert result == ""


class TestHealthcheck:
    def test_unhealthy_when_no_docker(self, backend):
        """healthcheck returns dict, doesn't raise."""
        with patch.object(backend, "_get_client", side_effect=SandboxSetupError("no docker")):
            result = backend.healthcheck()
        assert result["status"] == "unhealthy"
        assert result["docker_available"] is False


class TestIsDockerAvailable:
    def test_returns_bool(self):
        result = is_docker_available()
        assert isinstance(result, bool)


# ──────────────────────────────────────────────────────────────
# Integration tests — only run when Docker daemon is available
# ──────────────────────────────────────────────────────────────


@pytest.fixture
def docker_backend_or_skip():
    """Skip tests if Docker is not available or image cannot be pulled."""
    if not is_docker_available():
        pytest.skip("Docker daemon not available")
    backend = DockerBackend(image="python:3.12-slim")
    try:
        import docker as docker_lib

        client = docker_lib.from_env()
        client.images.pull("python:3.12-slim")
    except Exception as e:
        pytest.skip(f"Docker image pull failed: {e}")
    return backend


@pytest.mark.slow
class TestDockerIntegration:
    """Real Docker execution tests — run with: pytest -m slow tests/sandbox/test_docker_backend.py"""

    def test_healthcheck_healthy(self, docker_backend_or_skip):
        result = docker_backend_or_skip.healthcheck()
        assert result["status"] == "healthy"

    def test_execute_simple_python(self, docker_backend_or_skip):
        """Execute a trivial Python script in Docker."""
        from omnievolve.sandbox.base import CommandSpec

        plan = EvaluationPlan(
            commands=[CommandSpec(argv=["python", "-c", "print('hello from docker')"])],
        )
        candidate = CandidateArtifact(
            candidate_id="test", source_hash="", manifest_hash=None, language="python"
        )
        policy = SandboxPolicy(
            timeout_sec=30,
            mem_limit_mb=256,
            pids_limit=100,
            cpu_limit=1.0,
            read_only_root=True,
            network_mode="none",
            run_as_non_root=True,
            drop_capabilities=True,
            no_new_privileges=True,
            allowed_env=set(),
            tmpfs_mb=64,
        )
        result = docker_backend_or_skip.execute(plan, candidate, policy)
        assert "hello from docker" in result.stdout
        assert result.return_codes[0] == 0
        assert not result.timed_out

    def test_execute_timeout(self, docker_backend_or_skip):
        """Timeout kills the container."""
        from omnievolve.sandbox.base import CommandSpec

        plan = EvaluationPlan(
            commands=[CommandSpec(argv=["python", "-c", "import time; time.sleep(100)"])],
        )
        candidate = CandidateArtifact(
            candidate_id="test", source_hash="", manifest_hash=None, language="python"
        )
        policy = SandboxPolicy(
            timeout_sec=2,
            mem_limit_mb=256,
            pids_limit=100,
            cpu_limit=1.0,
            read_only_root=True,
            network_mode="none",
            run_as_non_root=True,
            drop_capabilities=True,
            no_new_privileges=True,
            allowed_env=set(),
            tmpfs_mb=64,
        )
        result = docker_backend_or_skip.execute(plan, candidate, policy)
        assert result.timed_out
