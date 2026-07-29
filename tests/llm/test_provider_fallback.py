from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace

from omnievolve.agents.llm_gateway import LLMEndpoint, LLMGateway


def test_authentication_failure_moves_to_distinct_provider(monkeypatch) -> None:
    calls: list[tuple[str, str | None, str | None]] = []

    class AuthenticationError(Exception):
        status_code = 401

    class StubLiteLLM(ModuleType):
        @staticmethod
        def completion(**kwargs):
            calls.append((kwargs["model"], kwargs["api_base"], kwargs["api_key"]))
            if kwargs["model"] == "primary":
                raise AuthenticationError("invalid key")
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="fallback-ok"))],
                usage=SimpleNamespace(prompt_tokens=2, completion_tokens=1, total_tokens=3),
                model_dump=lambda: {},
            )

    monkeypatch.setitem(sys.modules, "litellm", StubLiteLLM("litellm"))
    gateway = LLMGateway(
        default_model="primary",
        api_key="primary-secret",
        api_base="https://primary.invalid/v1",
        fallback_endpoints=[
            LLMEndpoint(
                model="fallback",
                api_key="fallback-secret",
                api_base="https://fallback.invalid/v1",
            )
        ],
        max_retries=3,
    )

    response = gateway.chat([{"role": "user", "content": "ping"}])

    assert response.model == "fallback"
    assert response.content == "fallback-ok"
    assert calls == [
        ("primary", "https://primary.invalid/v1", "primary-secret"),
        ("fallback", "https://fallback.invalid/v1", "fallback-secret"),
    ]


def test_fallback_secret_is_redacted() -> None:
    gateway = LLMGateway(
        fallback_endpoints=[LLMEndpoint("fallback", "fallback-secret", "https://fallback")]
    )
    assert gateway._redact_error(RuntimeError("bad fallback-secret")) == "bad [REDACTED]"  # noqa: SLF001


def test_permanent_model_error_skips_retries(monkeypatch) -> None:
    calls: list[str] = []

    class ModelDeniedError(Exception):
        status_code = 403

    class StubLiteLLM(ModuleType):
        @staticmethod
        def completion(**kwargs):
            calls.append(kwargs["model"])
            if kwargs["model"] == "primary":
                raise ModelDeniedError("Model access denied")
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))],
                usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=2),
                model_dump=lambda: {},
            )

    monkeypatch.setitem(sys.modules, "litellm", StubLiteLLM("litellm"))
    gateway = LLMGateway(
        default_model="primary",
        fallback_endpoints=[LLMEndpoint("fallback", "other-key", "https://other")],
        max_retries=5,
    )

    assert gateway.chat([{"role": "user", "content": "ping"}]).model == "fallback"
    assert calls == ["primary", "fallback"]
