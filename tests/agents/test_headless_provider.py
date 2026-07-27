"""HeadlessProvider 测试 — Step 9: 0% → 70%+."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from omnievolve.agents.headless_provider import (
    HeadlessModel,
    _build_command,
    check_headless_available,
    parse_headless_model,
    query_headless,
)


class TestParseHeadlessModel:
    """parse_headless_model 格式解析."""

    def test_agent_only(self):
        hm = parse_headless_model("headless/claude-code")
        assert hm.agent == "claude-code"
        assert hm.model is None
        assert hm.params == {}

    def test_agent_with_model(self):
        hm = parse_headless_model("headless/codex@gpt-4o")
        assert hm.agent == "codex"
        assert hm.model == "gpt-4o"

    def test_agent_with_model_and_params(self):
        hm = parse_headless_model("headless/claude-code@sonnet?effort=high")
        assert hm.agent == "claude-code"
        assert hm.model == "sonnet"
        assert hm.params == {"effort": "high"}

    def test_colon_prefix(self):
        hm = parse_headless_model("headless:aider")
        assert hm.agent == "aider"

    def test_multiple_params(self):
        hm = parse_headless_model("headless/codex@gpt-4o?effort=high&temp=0.5")
        assert hm.params == {"effort": "high", "temp": "0.5"}


class TestBuildCommand:
    """_build_command 命令构建."""

    def test_claude_code(self):
        hm = HeadlessModel(agent="claude-code", model=None, params={})
        cmd = _build_command(hm, "/tmp/prompt.txt")
        assert cmd[0] == "claude"
        assert "--print" in cmd

    def test_codex_with_model(self):
        hm = HeadlessModel(agent="codex", model="gpt-4o", params={})
        cmd = _build_command(hm, "/tmp/prompt.txt")
        assert "codex" in cmd
        assert "--model" in cmd
        assert "gpt-4o" in cmd

    def test_unknown_agent(self):
        hm = HeadlessModel(agent="custom-tool", model=None, params={})
        cmd = _build_command(hm, "/tmp/prompt.txt")
        assert cmd[0] == "custom-tool"


class TestCheckHeadlessAvailable:
    """check_headless_available 可用性检查."""

    @patch("omnievolve.agents.headless_provider.subprocess.run")
    def test_available(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        assert check_headless_available("claude-code") is True

    @patch("omnievolve.agents.headless_provider.subprocess.run")
    def test_not_available(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1)
        assert check_headless_available("claude-code") is False

    @patch("omnievolve.agents.headless_provider.subprocess.run")
    def test_exception(self, mock_run):
        mock_run.side_effect = FileNotFoundError
        assert check_headless_available("nonexistent") is False


class TestQueryHeadless:
    """query_headless 查询."""

    @patch("omnievolve.agents.headless_provider.check_headless_available")
    def test_not_available_raises(self, mock_check):
        mock_check.return_value = False
        with pytest.raises(RuntimeError, match="not found"):
            query_headless("test prompt", "headless/claude-code")

    @patch("omnievolve.agents.headless_provider.subprocess.run")
    @patch("omnievolve.agents.headless_provider.check_headless_available")
    def test_success(self, mock_check, mock_run):
        mock_check.return_value = True
        mock_run.return_value = MagicMock(returncode=0, stdout="generated code", stderr="")
        result = query_headless("test prompt", "headless/claude-code")
        assert result == "generated code"

    @patch("omnievolve.agents.headless_provider.subprocess.run")
    @patch("omnievolve.agents.headless_provider.check_headless_available")
    def test_timeout(self, mock_check, mock_run):
        import subprocess

        mock_check.return_value = True
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="claude", timeout=120)
        with pytest.raises(RuntimeError, match="timed out"):
            query_headless("test prompt", "headless/claude-code")
