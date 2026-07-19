"""Critic Agent - 静态审查.

S5-08: 实现 CriticAgent 静态审查
"""

from __future__ import annotations

import ast
import json
import logging

from omnievolve.agents.base import CodeOutput, ThoughtOutput
from omnievolve.agents.llm_gateway import LLMGateway

logger = logging.getLogger(__name__)

CRITIC_SYSTEM_PROMPT = """You are the Critic Agent in an evolutionary code optimization system.
Your role is to review the generated code for correctness and quality.

Check for:
1. Syntax errors
2. Logic errors
3. Security issues
4. Performance concerns
5. Alignment with the improvement thought

Output format (JSON):
{
    "passed": true/false,
    "feedback": "Detailed feedback",
    "issues": ["issue1", "issue2"]
}
"""


class Critic:
    """Critic Agent - 负责静态审查."""

    def __init__(
        self,
        llm: LLMGateway | None = None,
        *,
        model: str | None = None,
        system_prompt: str | None = None,
        use_syntax_check: bool = True,
    ) -> None:
        self._llm = llm
        self._model = model
        self._system_prompt = system_prompt or CRITIC_SYSTEM_PROMPT
        self._use_syntax_check = use_syntax_check

    def review(self, code: CodeOutput, thought: ThoughtOutput) -> tuple[bool, str]:
        """审查代码.

        Returns:
            (passed, feedback)
        """
        issues = []

        # 1. 语法检查
        if self._use_syntax_check:
            syntax_ok, syntax_error = self._check_syntax(code.full_code)
            if not syntax_ok:
                issues.append(f"Syntax error: {syntax_error}")

        # 2. 基础静态检查
        static_issues = self._static_check(code.full_code)
        issues.extend(static_issues)

        # 3. LLM 审查（如果可用）
        if self._llm and not issues:
            llm_passed, llm_feedback = self._llm_review(code, thought)
            if not llm_passed:
                issues.append(llm_feedback)

        if issues:
            return False, "; ".join(issues)
        return True, "Code passed review"

    def _check_syntax(self, code: str) -> tuple[bool, str]:
        """Python 语法检查."""
        try:
            ast.parse(code)
            return True, ""
        except SyntaxError as e:
            return False, f"Line {e.lineno}: {e.msg}"

    def _static_check(self, code: str) -> list[str]:
        """基础静态检查."""
        issues = []

        # 检查危险导入
        dangerous_imports = ["os.system", "subprocess.call", "eval(", "exec("]
        for imp in dangerous_imports:
            if imp in code:
                issues.append(f"Potentially dangerous: {imp}")

        # 检查无限循环模式
        if "while True:" in code and "break" not in code:
            issues.append("Potential infinite loop without break")

        return issues

    def _llm_review(self, code: CodeOutput, thought: ThoughtOutput) -> tuple[bool, str]:
        """LLM 审查."""
        if not self._llm:
            return True, ""

        user_message = f"""## Thought:
{thought.thought}

## Code:
```python
{code.full_code[:5000]}
```

Review this code for correctness and alignment with the thought."""

        messages = [
            {"role": "system", "content": self._system_prompt},
            {"role": "user", "content": user_message},
        ]

        response = self._llm.chat(
            messages,
            model=self._model,
            temperature=0.2,
            agent_role="critic",
        )

        try:
            data = json.loads(response.content)
            return data.get("passed", True), data.get("feedback", "")
        except json.JSONDecodeError:
            return True, response.content
