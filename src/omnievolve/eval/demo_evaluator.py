"""Python Demo Evaluator.

S3-10: 实现 Python demo evaluator
- 单元测试式评估
- 用于演示和测试
"""

from __future__ import annotations

import json

from omnievolve.eval.task_evaluator import (
    CandidateArtifact,
    CommandSpec,
    EvalOutput,
    EvaluationContext,
    EvaluationPlan,
    SandboxExecutionResult,
)


class PythonUnitTestEvaluator:
    """Python 单元测试评估器.

    通过运行 pytest 评估候选代码。
    """

    version_id = "python-unittest@1.0.0"

    def __init__(
        self,
        test_command: list[str] | None = None,
        timeout_sec: float = 30.0,
    ) -> None:
        """初始化.

        Args:
            test_command: 测试命令（默认 pytest）
            timeout_sec: 超时时间
        """
        self._test_command = test_command or ["python", "-m", "pytest", "-v"]
        self._timeout_sec = timeout_sec

    def build_plan(
        self,
        candidate: CandidateArtifact,
        context: EvaluationContext,
    ) -> EvaluationPlan:
        """构建评估计划."""
        return EvaluationPlan(
            commands=[
                CommandSpec(
                    argv=self._test_command,
                    timeout_sec=self._timeout_sec,
                ),
            ],
            expected_outputs=[],
            network_access=False,
        )

    def parse_result(
        self,
        result: SandboxExecutionResult,
        context: EvaluationContext,
    ) -> EvalOutput:
        """解析执行结果."""
        # 检查是否超时
        if result.timed_out:
            return EvalOutput(
                score=0.0,
                metrics={},
                passed=False,
                failure_reason="Execution timed out",
            )

        # 检查返回码
        if not result.return_codes or result.return_codes[0] != 0:
            return EvalOutput(
                score=0.0,
                metrics={},
                passed=False,
                failure_reason=result.stderr[-2000:] if result.stderr else "Non-zero exit code",
            )

        # 尝试从输出解析测试结果
        passed, total = self._parse_pytest_output(result.stdout)

        if total > 0:
            score = passed / total
        else:
            score = 1.0 if result.return_codes[0] == 0 else 0.0

        return EvalOutput(
            score=score,
            metrics={
                "tests_passed": float(passed),
                "tests_total": float(total),
                "execution_time_ms": result.execution_time_ms,
            },
            passed=passed == total and total > 0,
        )

    def get_baseline(self) -> float:
        """基线分数."""
        return 0.5  # 假设 50% 测试通过为基线

    def _parse_pytest_output(self, stdout: str) -> tuple[int, int]:
        """解析 pytest 输出，返回 (passed, total)."""
        import re

        # 匹配 "X passed" 模式
        passed_match = re.search(r"(\d+) passed", stdout)
        failed_match = re.search(r"(\d+) failed", stdout)
        error_match = re.search(r"(\d+) error", stdout)

        passed = int(passed_match.group(1)) if passed_match else 0
        failed = int(failed_match.group(1)) if failed_match else 0
        errors = int(error_match.group(1)) if error_match else 0

        total = passed + failed + errors
        return passed, total


class SimpleScoreEvaluator:
    """简单分数评估器.

    直接运行候选代码并解析 JSON 输出中的 score 字段。
    """

    version_id = "simple-score@1.0.0"

    def __init__(
        self,
        run_command: list[str] | None = None,
        timeout_sec: float = 30.0,
    ) -> None:
        self._run_command = run_command or ["python", "main.py"]
        self._timeout_sec = timeout_sec

    def build_plan(
        self,
        candidate: CandidateArtifact,
        context: EvaluationContext,
    ) -> EvaluationPlan:
        return EvaluationPlan(
            commands=[
                CommandSpec(
                    argv=self._run_command,
                    timeout_sec=self._timeout_sec,
                ),
            ],
            expected_outputs=["result.json"],
            network_access=False,
        )

    def parse_result(
        self,
        result: SandboxExecutionResult,
        context: EvaluationContext,
    ) -> EvalOutput:
        if result.timed_out:
            return EvalOutput(
                score=0.0,
                metrics={},
                passed=False,
                failure_reason="Timeout",
            )

        if result.return_codes and result.return_codes[0] != 0:
            return EvalOutput(
                score=0.0,
                metrics={},
                passed=False,
                failure_reason=result.stderr[-2000:],
            )

        # 尝试解析 result.json
        if "result.json" in result.output_artifacts:
            try:
                # 需要从 artifact store 加载，这里简化处理
                pass
            except Exception:
                pass

        # 尝试从 stdout 解析 JSON
        try:
            data = json.loads(result.stdout)
            score = float(data.get("score", 0.0))
            return EvalOutput(
                score=score,
                metrics=data,
                passed=score > 0,
            )
        except (json.JSONDecodeError, ValueError):
            pass

        # 回退：成功执行即得分
        return EvalOutput(
            score=1.0,
            metrics={"execution_time_ms": result.execution_time_ms},
            passed=True,
        )

    def get_baseline(self) -> float:
        return 0.0
