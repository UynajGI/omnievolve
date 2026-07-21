"""Critic Agent - 静态审查 + 执行反馈审查.

S5-08: 实现 CriticAgent 静态审查
P0-2: 沙箱执行反馈增强 — Critic 可基于上一轮 stderr 判断修复有效性
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

CRITIC_EXECUTION_REVIEW_PROMPT = """You are the Critic Agent in an evolutionary code optimization system.
The previous version of this code FAILED during sandbox execution.

Your job is to verify:
1. Does the new code correctly address the previous runtime error?
2. Does the fix introduce any NEW issues (new exceptions, logic regressions)?
3. Are there any remaining syntax/logic/security problems?

Be strict: if the previous error pattern is still present in the new code, REJECT it.

Output format (JSON):
{
    "passed": true/false,
    "feedback": "Detailed feedback explaining whether the fix addresses the error",
    "issues": ["issue1", "issue2"],
    "addresses_previous_error": true/false
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

    def review(
        self,
        code: CodeOutput,
        thought: ThoughtOutput,
        last_eval_stderr: str = "",
    ) -> tuple[bool, str]:
        """审查代码.

        Args:
            code: 待审查代码.
            thought: 改进思想.
            last_eval_stderr: P0-2 — 上一轮沙箱执行的 stderr/失败信息.
                非空时启用执行反馈增强审查.

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
            if last_eval_stderr:
                # P0-2: 执行反馈增强审查
                llm_passed, llm_feedback = self._llm_review_with_execution(
                    code, thought, last_eval_stderr
                )
            else:
                llm_passed, llm_feedback = self._llm_review(code, thought)
            if not llm_passed:
                issues.append(llm_feedback)

        if issues:
            return False, "; ".join(issues)
        return True, "Code passed review"

    def review_with_execution_result(
        self,
        code: CodeOutput,
        thought: ThoughtOutput,
        last_eval_stderr: str,
    ) -> tuple[bool, str]:
        """P0-2: 带执行反馈的审查（显式入口）.

        当上一轮评估失败时调用，Critic 额外检查：
        a) 新代码是否正确处理了上次报错？
        b) 修复是否引入了新问题？

        Args:
            code: 待审查代码.
            thought: 改进思想.
            last_eval_stderr: 上一轮沙箱 stderr（截取后 500 字）.

        Returns:
            (passed, feedback)
        """
        return self.review(code, thought, last_eval_stderr=last_eval_stderr)

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

    def _llm_review_with_execution(
        self,
        code: CodeOutput,
        thought: ThoughtOutput,
        last_eval_stderr: str,
    ) -> tuple[bool, str]:
        """P0-2: 带执行反馈的 LLM 审查.

        向 LLM 提供上一轮 stderr，让其判断新代码是否修复了根因。
        """
        if not self._llm:
            return True, ""

        # 截取 stderr 后 500 字（最有价值的错误通常在末尾）
        stderr_tail = last_eval_stderr[-500:] if len(last_eval_stderr) > 500 else last_eval_stderr

        user_message = f"""## Previous Execution Error (stderr):
```
{stderr_tail}
```

## Improvement Thought:
{thought.thought}

## New Code (supposed fix):
```python
{code.full_code[:5000]}
```

## Your Task:
1. Does this new code fix the root cause of the error above?
2. Does it introduce any NEW issues?
3. Is the fix complete and correct?

Be strict — if the error pattern is still present, REJECT."""

        messages = [
            {"role": "system", "content": CRITIC_EXECUTION_REVIEW_PROMPT},
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
            passed = data.get("passed", True)
            feedback = data.get("feedback", "")
            # 额外检查：如果 LLM 认为没有解决前次错误，强制不通过
            if not data.get("addresses_previous_error", True):
                passed = False
                if "previous error" not in feedback.lower():
                    feedback = f"Code does not address previous error. {feedback}"
            return passed, feedback
        except json.JSONDecodeError:
            return True, response.content
