"""MontyBackend 单元测试 — Step 10."""

from __future__ import annotations

import pytest

try:
    import pydantic_monty  # noqa: F401
    MONTY_AVAILABLE = True
except ImportError:
    MONTY_AVAILABLE = False


class TestMontyUnit:
    """MontyBackend 测试."""

    def test_import_module(self):
        from omnievolve.sandbox import monty_backend
        assert monty_backend is not None

    def test_class_exists(self):
        from omnievolve.sandbox.monty_backend import MontyBackend
        assert MontyBackend is not None

    @pytest.mark.skipif(not MONTY_AVAILABLE, reason="pydantic-monty not installed")
    def test_init_with_monty(self):
        from omnievolve.sandbox.monty_backend import MontyBackend
        backend = MontyBackend()
        assert backend is not None

    @pytest.mark.skipif(not MONTY_AVAILABLE, reason="pydantic-monty not installed")
    def test_environment_version_id(self):
        from omnievolve.sandbox.monty_backend import MontyBackend
        backend = MontyBackend()
        assert isinstance(backend.environment_version_id, str)

    @pytest.mark.skipif(not MONTY_AVAILABLE, reason="pydantic-monty not installed")
    def test_healthcheck(self):
        from omnievolve.sandbox.monty_backend import MontyBackend
        backend = MontyBackend()
        health = backend.healthcheck()
        assert isinstance(health, dict)
        assert "status" in health
