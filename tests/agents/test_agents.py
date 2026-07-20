"""Sprint 5 测试: Agents + LLM Gateway."""

import pytest

from omnievolve.agents.base import AgentContext, CodeOutput, ThoughtOutput
from omnievolve.agents.coder import Coder
from omnievolve.agents.critic import Critic
from omnievolve.agents.director import Director
from omnievolve.agents.llm_gateway import FakeLLM

pytestmark = pytest.mark.unit


@pytest.fixture
def fake_llm():
    """Fake LLM for testing."""
    return FakeLLM(
        responses=[
            '{"thought": "Use memoization", "rationale": "Avoid redundant calculations", "confidence": 0.8, "mechanism_tags": ["dp"]}',
            '{"full_code": "def solve():\\n    return 42", "diff": "Added memoization", "explanation": "Cached results"}',
            '{"passed": true, "feedback": "Looks good"}',
        ]
    )


@pytest.fixture
def agent_context():
    """测试用 AgentContext."""
    return AgentContext(
        experiment_id="exp1",
        task_id="task1",
        generation=1,
        parent_thoughts=["Try dynamic programming"],
        domain_hints=["This is an optimization problem"],
    )


class TestFakeLLM:
    """FakeLLM 测试."""

    def test_returns_preset_responses(self, fake_llm):
        """返回预设响应."""
        response = fake_llm.chat([{"role": "user", "content": "test"}])
        assert "memoization" in response.content

    def test_tracks_calls(self, fake_llm):
        """追踪调用."""
        fake_llm.chat([{"role": "user", "content": "test1"}])
        fake_llm.chat([{"role": "user", "content": "test2"}])

        assert len(fake_llm.calls) == 2


class TestDirector:
    """Director 测试."""

    def test_evolve_thought(self, fake_llm, agent_context):
        """进化思想."""
        director = Director(fake_llm)
        thought = director.evolve_thought(agent_context)

        assert isinstance(thought, ThoughtOutput)
        assert "memoization" in thought.thought.lower()
        assert thought.confidence == 0.8
        assert "dp" in thought.mechanism_tags

    def test_handles_invalid_json(self, agent_context):
        """处理无效 JSON."""
        llm = FakeLLM(responses=["This is not JSON"])
        director = Director(llm)

        thought = director.evolve_thought(agent_context)

        assert thought.thought == "This is not JSON"
        assert thought.confidence == 0.5


class TestCoder:
    """Coder 测试."""

    def test_generate_code(self, fake_llm, agent_context):
        """生成代码."""
        # 跳过第一个响应（Director 用）
        fake_llm.chat([])

        coder = Coder(fake_llm)
        thought = ThoughtOutput(
            thought="Use memoization",
            rationale="Avoid redundant calculations",
        )

        code = coder.generate_code(agent_context, thought)

        assert isinstance(code, CodeOutput)
        assert "def solve" in code.full_code

    def test_handles_plain_code(self, agent_context):
        """处理纯代码响应."""
        llm = FakeLLM(responses=["def hello():\n    print('world')"])
        coder = Coder(llm)
        thought = ThoughtOutput(thought="test", rationale="test")

        code = coder.generate_code(agent_context, thought)

        assert "def hello" in code.full_code


class TestCritic:
    """Critic 测试."""

    def test_review_valid_code(self):
        """审查有效代码."""
        critic = Critic(use_syntax_check=True)
        code = CodeOutput(
            diff="",
            full_code="def solve():\n    return 42",
        )
        thought = ThoughtOutput(thought="test", rationale="test")

        passed, feedback = critic.review(code, thought)

        assert passed
        assert "passed" in feedback.lower()

    def test_review_syntax_error(self):
        """审查语法错误."""
        critic = Critic(use_syntax_check=True)
        code = CodeOutput(
            diff="",
            full_code="def solve(\n    return 42",  # 语法错误
        )
        thought = ThoughtOutput(thought="test", rationale="test")

        passed, feedback = critic.review(code, thought)

        assert not passed
        assert "syntax" in feedback.lower()

    def test_review_dangerous_code(self):
        """审查危险代码."""
        critic = Critic(use_syntax_check=True)
        code = CodeOutput(
            diff="",
            full_code="import os\nos.system('rm -rf /')",
        )
        thought = ThoughtOutput(thought="test", rationale="test")

        passed, feedback = critic.review(code, thought)

        assert not passed
        assert "dangerous" in feedback.lower()


class TestAgentProtocols:
    """Agent Protocol 测试."""

    def test_director_implements_protocol(self, fake_llm):
        """Director 实现 DirectorAgent 协议."""
        from omnievolve.agents.base import DirectorAgent

        director = Director(fake_llm)
        assert isinstance(director, DirectorAgent)

    def test_coder_implements_protocol(self, fake_llm):
        """Coder 实现 CoderAgent 协议."""
        from omnievolve.agents.base import CoderAgent

        coder = Coder(fake_llm)
        assert isinstance(coder, CoderAgent)

    def test_critic_implements_protocol(self):
        """Critic 实现 CriticAgent 协议."""
        from omnievolve.agents.base import CriticAgent

        critic = Critic()
        assert isinstance(critic, CriticAgent)
