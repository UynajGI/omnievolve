"""LLMGateway.score_tokens 与 capability probe 测试（集成计划 §6.3/§7）."""

from __future__ import annotations

import math

import pytest

from omnievolve.agents.llm_gateway import FakeLLM, LLMGateway
from omnievolve.eval.verifier_capability import (
    CapabilityProbeResult,
    VerifierCapabilityProbe,
)
from omnievolve.exceptions import LLMVerifierCapabilityError


class _FakeCompletion:
    """模拟 litellm.completion 的 OpenAI-compatible 响应."""

    def __init__(self, *, positions, ignored_logprobs=False, no_top_logprobs=False):
        self._positions = positions
        self._ignored_logprobs = ignored_logprobs

        class Logprobs:
            def __init__(self):
                if ignored_logprobs:
                    self.content = None
                    return
                self.content = [
                    {
                        "token": token,
                        "logprob": logprob,
                        "top_logprobs": (
                            None
                            if no_top_logprobs
                            else [
                                {"token": t, "logprob": lp}
                                for t, lp in distribution.items()
                            ]
                        ),
                    }
                    for token, logprob, distribution in positions
                ]

        class Choice:
            def __init__(self):
                self.logprobs = Logprobs()

                class Message:
                    content = "".join(p[0] for p in positions)

                self.message = Message()

        class Usage:
            prompt_tokens = 10
            completion_tokens = len(positions)
            total_tokens = 10 + len(positions)

        class Response:
            def __init__(self):
                self.choices = [Choice()]
                self.usage = Usage()
                self._hidden_params = {}

        self.response = Response()

    def model_dump(self):
        return {}


@pytest.fixture
def fake_gateway():
    return LLMGateway(default_model="verifier-model")


def _dist(tokens: dict[str, float]) -> dict[str, float]:
    """{token: probability} → {token: logprob}（模拟 provider top_logprobs）."""
    import math

    return {token: math.log(probability) for token, probability in tokens.items()}


class TestScoreTokens:
    def test_parses_token_logprobs(self, fake_gateway, monkeypatch):
        import litellm

        positions = [
            ("7", 0.0, _dist({"7": 0.9, "6": 0.1})),
            ("8", 0.0, _dist({"8": 0.8, "7": 0.2})),
        ]
        monkeypatch.setattr(litellm, "completion", lambda **kw: _FakeCompletion(positions=positions).response)
        response = fake_gateway.score_tokens(
            [{"role": "user", "content": "score"}],
            score_tokens=("6", "7", "8"),
            model="verifier-model",
            top_logprobs=2,
            experiment_id="e",
            prompt_version_id="p",
            granularity=2,
        )
        assert response.actual_tokens == ("7", "8")
        assert len(response.per_position_probabilities) == 2
        assert response.per_position_probabilities[0]["7"] == pytest.approx(0.9)
        # 两个位置的 top-K 全部落在评分集合：coverage = (1.0 + 1.0) / 2。
        # （修正后按 top-K 全部评分 token 的概率质量计算，而非只取
        # actual token 自身概率 (0.9 + 0.8) / 2。）
        assert response.probability_coverage == pytest.approx(1.0)

    def test_parses_litellm_native_logprob_objects(self, fake_gateway, monkeypatch):
        """LiteLLM 返回 pydantic TokenLogprob/TopLogprob 对象（不可下标）.

        回归：旧实现用 ``t["token"]``/``item.get(...)`` 直接下标，任一
        真实 provider 响应都会 ``TypeError: 'TopLogprob' object is not
        subscriptable``。
        """
        litellm = pytest.importorskip("litellm")
        from litellm.types.utils import ChatCompletionTokenLogprob, TopLogprob

        class Logprobs:
            def __init__(self):
                self.content = [
                    ChatCompletionTokenLogprob(
                        token="7",
                        logprob=math.log(0.9),
                        top_logprobs=[
                            TopLogprob(token="7", logprob=math.log(0.9)),
                            TopLogprob(token="6", logprob=math.log(0.1)),
                        ],
                    )
                ]

        class Choice:
            logprobs = Logprobs()

            class Message:
                content = "7"

            message = Message()

        class Usage:
            prompt_tokens = 10
            completion_tokens = 1
            total_tokens = 11

        class Response:
            choices = [Choice()]
            usage = Usage()
            _hidden_params = {}

            def model_dump(self):
                return {}

        monkeypatch.setattr(litellm, "completion", lambda **kw: Response())
        response = fake_gateway.score_tokens(
            [{"role": "user", "content": "score"}],
            score_tokens=("6", "7"),
            model="verifier-model",
            top_logprobs=2,
            experiment_id="e",
            prompt_version_id="p",
            granularity=1,
        )
        assert response.actual_tokens == ("7",)
        assert response.per_position_probabilities[0]["7"] == pytest.approx(0.9)
        assert response.probability_coverage == pytest.approx(1.0)

    def test_ignored_logprobs_is_capability_error(self, fake_gateway, monkeypatch):
        import litellm

        monkeypatch.setattr(
            litellm,
            "completion",
            lambda **kw: _FakeCompletion(positions=[("7", 0.0, _dist({"7": 1.0}))], ignored_logprobs=True).response,
        )
        with pytest.raises(LLMVerifierCapabilityError, match="ignored logprobs"):
            fake_gateway.score_tokens(
                [{"role": "user", "content": "score"}],
                score_tokens=("7",),
                model="verifier-model",
                top_logprobs=1,
                experiment_id="e",
                prompt_version_id="p",
            )

    def test_dropped_top_logprobs_is_capability_error(self, fake_gateway, monkeypatch):
        import litellm

        positions = [("7", 0.0, _dist({"7": 1.0}))]
        monkeypatch.setattr(
            litellm,
            "completion",
            lambda **kw: _FakeCompletion(positions=positions, no_top_logprobs=True).response,
        )
        with pytest.raises(LLMVerifierCapabilityError, match="dropped top_logprobs"):
            fake_gateway.score_tokens(
                [{"role": "user", "content": "score"}],
                score_tokens=("7",),
                model="verifier-model",
                top_logprobs=1,
                experiment_id="e",
                prompt_version_id="p",
            )

    def test_score_token_not_emittable_is_capability_error(self, fake_gateway, monkeypatch):
        import litellm

        positions = [("x", 0.0, _dist({"x": 1.0}))]
        monkeypatch.setattr(
            litellm,
            "completion",
            lambda **kw: _FakeCompletion(positions=positions).response,
        )
        with pytest.raises(LLMVerifierCapabilityError, match="cannot emit"):
            fake_gateway.score_tokens(
                [{"role": "user", "content": "score"}],
                score_tokens=("7", "8"),
                model="verifier-model",
                top_logprobs=1,
                experiment_id="e",
                prompt_version_id="p",
            )

    def test_drop_params_never_requested(self, fake_gateway, monkeypatch):
        import litellm

        captured = {}
        positions = [("7", 0.0, _dist({"7": 1.0}))]

        def fake_completion(**kwargs):
            captured.update(kwargs)
            return _FakeCompletion(positions=positions).response

        monkeypatch.setattr(litellm, "completion", fake_completion)
        fake_gateway.score_tokens(
            [{"role": "user", "content": "score"}],
            score_tokens=("7",),
            model="verifier-model",
            top_logprobs=1,
            experiment_id="e",
            prompt_version_id="p",
        )
        assert captured["logprobs"] is True
        assert captured["top_logprobs"] == 1
        assert captured["drop_params"] is False

    def test_records_verifier_role_in_ledger(self, monkeypatch, db):
        import litellm

        gateway = LLMGateway(db=db, default_model="verifier-model")
        positions = [("7", 0.0, _dist({"7": 1.0}))]
        monkeypatch.setattr(
            litellm,
            "completion",
            lambda **kw: _FakeCompletion(positions=positions).response,
        )
        gateway.score_tokens(
            [{"role": "user", "content": "score"}],
            score_tokens=("7",),
            model="verifier-model",
            top_logprobs=1,
            experiment_id=None,
            prompt_version_id=None,
        )
        rows = db.fetchall("SELECT agent_role FROM llm_call_ledger")
        assert len(rows) == 1
        assert rows[0]["agent_role"] == "verifier"


class TestFakeLLMScoreTokens:
    def test_deterministic_for_same_request(self):
        fake = FakeLLM(score_token_probabilities={"10": 0.8, "12": 0.2})
        messages = [{"role": "user", "content": "score A vs B"}]
        first = fake.score_tokens(
            messages,
            score_tokens=("10", "12"),
            model="fake",
            top_logprobs=1,
            experiment_id="e",
            prompt_version_id="p",
        )
        second = fake.score_tokens(
            messages,
            score_tokens=("10", "12"),
            model="fake",
            top_logprobs=1,
            experiment_id="e",
            prompt_version_id="p",
        )
        assert first.actual_tokens == second.actual_tokens
        assert first.per_position_probabilities == second.per_position_probabilities
        assert first.probability_coverage == second.probability_coverage

    def test_fixture_probabilities_used(self):
        fake = FakeLLM(score_token_probabilities={"10": 0.9, "12": 0.1})
        response = fake.score_tokens(
            [{"role": "user", "content": "score"}],
            score_tokens=("10", "12"),
            model="fake",
            top_logprobs=1,
            experiment_id="e",
            prompt_version_id="p",
            granularity=1,
        )
        assert response.per_position_probabilities[0]["10"] == pytest.approx(0.9)

    def test_roles_recorded(self):
        fake = FakeLLM()
        fake.score_tokens(
            [{"role": "user", "content": "score"}],
            score_tokens=("10",),
            model="fake",
            top_logprobs=1,
            experiment_id="e",
            prompt_version_id="p",
        )
        assert fake.calls[-1]["agent_role"] == "verifier"


class TestCapabilityProbe:
    def test_native_logprobs_result(self, monkeypatch):
        import litellm

        gateway = LLMGateway(default_model="verifier-model")
        positions = [("10", 0.0, _dist({"10": 1.0}))]
        monkeypatch.setattr(
            litellm,
            "completion",
            lambda **kw: _FakeCompletion(positions=positions).response,
        )
        probe = VerifierCapabilityProbe(gateway)
        result = probe.probe("verifier-model")
        assert isinstance(result, CapabilityProbeResult)
        assert result.status == "native_logprobs"
        assert result.max_top_logprobs >= 5
        assert result.probability_coverage > 0
        assert result.capability_hash

    def test_unsupported_when_logprobs_ignored(self, monkeypatch):
        import litellm

        gateway = LLMGateway(default_model="verifier-model")
        monkeypatch.setattr(
            litellm,
            "completion",
            lambda **kw: _FakeCompletion(
                positions=[("10", 0.0, _dist({"10": 1.0}))],
                ignored_logprobs=True,
            ).response,
        )
        probe = VerifierCapabilityProbe(gateway)
        result = probe.probe("verifier-model")
        assert result.status == "unsupported"
        assert result.max_top_logprobs == 0

    def test_auth_errors_propagate_not_unsupported(self, monkeypatch):
        """鉴权/超时等环境错误向上传播，不得误判为能力缺失（§13）."""
        import litellm

        from omnievolve.exceptions import LLMAuthenticationError

        gateway = LLMGateway(default_model="verifier-model")

        def failing_completion(**kwargs):
            del kwargs
            raise LLMAuthenticationError("invalid api key")

        monkeypatch.setattr(litellm, "completion", failing_completion)
        probe = VerifierCapabilityProbe(gateway)
        with pytest.raises(LLMAuthenticationError, match="invalid api key"):
            probe.probe("verifier-model")

    def test_capability_hash_stable(self):
        from omnievolve.eval.verifier_capability import compute_capability_hash

        a = compute_capability_hash(
            model="m", api_base=None, max_top_logprobs=20, probability_coverage=0.95
        )
        b = compute_capability_hash(
            model="m", api_base=None, max_top_logprobs=20, probability_coverage=0.95
        )
        assert a == b
