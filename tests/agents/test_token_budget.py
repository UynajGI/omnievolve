"""1.1 token 预算化测试：角色级 max_tokens + 输出完整性守卫.

改进计划 §1.1 — 推理/输出 token 预算化：
- LLMGateway 按 agent_role 应用角色级输出预算（低于全局上限）；
- finish_reason=="length" 且仍有全局余量时自动扩容重试（截断守卫）；
- config 支持 role_max_tokens 且 TOML 部分覆盖与默认合并。
"""

from __future__ import annotations

import pytest

from omnievolve.agents.llm_gateway import LLMGateway
from omnievolve.config import DEFAULT_ROLE_MAX_TOKENS, ModelsSettings, load_settings

pytestmark = pytest.mark.unit


class _FakeChatCompletion:
    """模拟 litellm.completion 响应（含 finish_reason 与 usage）."""

    def __init__(self, content: str, finish_reason: str | None = None):
        class Message:
            def __init__(self):
                self.content = content

        class Choice:
            def __init__(self):
                self.message = Message()
                self.finish_reason = finish_reason

        class Usage:
            prompt_tokens = 10
            completion_tokens = 20
            total_tokens = 30

        self.choices = [Choice()]
        self.usage = Usage()

    def model_dump(self) -> dict:
        return {}


@pytest.fixture
def gateway():
    """角色预算网关：director=1024 / coder=2048，全局上限 8192."""
    return LLMGateway(
        default_model="test-model",
        default_max_tokens=8192,
        role_max_tokens={"director": 1024, "coder": 2048},
        max_retries=2,
        retry_backoff_base=0.01,
    )


def _patch_completion(monkeypatch, responses):
    """patch litellm.completion，返回 (调用记录, 顺序响应)."""
    import litellm

    calls: list[dict] = []
    index = 0

    def fake_completion(**kwargs):
        nonlocal index
        calls.append(kwargs)
        response = responses[index % len(responses)]
        index += 1
        return response

    monkeypatch.setattr(litellm, "completion", fake_completion)
    return calls


class TestRoleMaxTokens:
    def test_role_budget_applied_when_not_explicit(self, gateway, monkeypatch):
        calls = _patch_completion(monkeypatch, [_FakeChatCompletion("ok", "stop")])
        gateway.chat([{"role": "user", "content": "hi"}], agent_role="coder")
        assert calls[-1]["max_tokens"] == 2048

    def test_unknown_role_falls_back_to_global_cap(self, gateway, monkeypatch):
        calls = _patch_completion(monkeypatch, [_FakeChatCompletion("ok", "stop")])
        gateway.chat([{"role": "user", "content": "hi"}], agent_role="verifier")
        assert calls[-1]["max_tokens"] == 8192

    def test_explicit_max_tokens_wins(self, gateway, monkeypatch):
        calls = _patch_completion(monkeypatch, [_FakeChatCompletion("ok", "stop")])
        gateway.chat(
            [{"role": "user", "content": "hi"}],
            agent_role="coder",
            max_tokens=512,
        )
        assert calls[-1]["max_tokens"] == 512

    def test_role_budget_clamped_to_global_cap(self, monkeypatch):
        _patch_completion(monkeypatch, [_FakeChatCompletion("ok", "stop")])
        gw = LLMGateway(
            default_model="test-model",
            default_max_tokens=2048,
            role_max_tokens={"coder": 99999},
        )
        assert gw._role_max_tokens["coder"] == 2048


class TestTruncationGuard:
    def test_retries_with_global_cap_on_truncation(self, gateway, monkeypatch):
        calls = _patch_completion(
            monkeypatch,
            [
                _FakeChatCompletion("part", finish_reason="length"),
                _FakeChatCompletion("full", finish_reason="stop"),
            ],
        )
        response = gateway.chat([{"role": "user", "content": "hi"}], agent_role="coder")

        assert [c["max_tokens"] for c in calls] == [2048, 8192]  # 角色预算 → 全局上限
        assert response.content == "full"
        assert response.truncated is False

    def test_truncated_flag_set_at_global_cap(self, monkeypatch):
        _patch_completion(
            monkeypatch,
            [_FakeChatCompletion("still cut", finish_reason="length")],
        )
        gw = LLMGateway(default_model="test-model", default_max_tokens=4096)
        response = gw.chat([{"role": "user", "content": "hi"}], agent_role="coder")
        assert response.truncated is True  # 已到全局上限，不再扩容

    def test_is_truncated_handles_dict_style_responses(self):
        """review 修复：dict 风格响应（测试/部分 provider）不应误判未截断."""
        assert LLMGateway._is_truncated({"choices": [{"finish_reason": "length"}]}) is True
        assert LLMGateway._is_truncated({"choices": [{"finish_reason": "stop"}]}) is False
        assert LLMGateway._is_truncated({"choices": []}) is False
        assert LLMGateway._is_truncated({}) is False
        # litellm 对象路径不受影响
        assert LLMGateway._is_truncated(_FakeChatCompletion("x", "length")) is True
        assert LLMGateway._is_truncated(_FakeChatCompletion("x", "stop")) is False


class TestConfig:
    def test_default_role_max_tokens(self):
        settings = ModelsSettings()
        assert settings.role_max_tokens == DEFAULT_ROLE_MAX_TOKENS
        assert settings.role_max_tokens["coder"] < settings.max_tokens

    def test_toml_partial_override_merges(self, tmp_path):
        config = tmp_path / "omnievolve.toml"
        config.write_text(
            "[models]\nrole_max_tokens = { coder = 8192 }\n",
            encoding="utf-8",
        )
        settings = load_settings(config)
        # 部分覆盖：coder 覆盖，其余保留默认
        assert settings.models.role_max_tokens["coder"] == 8192
        assert settings.models.role_max_tokens["director"] == DEFAULT_ROLE_MAX_TOKENS["director"]
