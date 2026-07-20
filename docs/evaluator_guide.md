# 评估器开发指南

> S3-15: 编写评估器开发指南

## 概述

TaskEvaluator 是 OmniEvolve 与具体任务之间的桥梁。它负责：
1. 构建声明式评估计划（`build_plan`）
2. 解析沙箱执行结果（`parse_result`）

**关键原则**: Evaluator 只能声明评估计划，不能绕过沙箱直接执行候选代码。

## 快速开始

```python
from omnievolve.eval.task_evaluator import (
    CandidateArtifact,
    EvalOutput,
    EvaluationContext,
    EvaluationPlan,
    CommandSpec,
    SandboxExecutionResult,
)

class MyEvaluator:
    version_id = "my-evaluator@1.0.0"

    def build_plan(self, candidate, context):
        return EvaluationPlan(
            commands=[
                CommandSpec(argv=["python", "main.py"]),
            ],
        )

    def parse_result(self, result, context):
        ok = result.return_codes and result.return_codes[0] == 0
        return EvalOutput(
            score=1.0 if ok else 0.0,
            metrics={"exit_code": result.return_codes[0] if result.return_codes else -1},
            passed=ok,
        )

    def get_baseline(self):
        return 0.5
```

## 必须实现的接口

### `version_id: str` (property)

唯一标识评估器版本。改变评估逻辑时必须更新此 ID，以确保评估结果的可追溯性。

```python
version_id = "sort-eval@2.1.0"
```

### `build_plan(candidate, context) -> EvaluationPlan`

根据候选代码和上下文构建声明式评估计划。返回一个 `EvaluationPlan`，包含：
- `commands`: 要执行的命令列表
- `mounts`: 数据集挂载（可选）
- `expected_outputs`: 预期输出文件列表（可选）
- `network_access`: 是否需要网络（默认 False）
- `resource_profile`: 资源配置文件

### `parse_result(result, context) -> EvalOutput`

解析沙箱执行结果。返回 `EvalOutput`：
- `score`: 主分数（越高越好，归一化到 [0, 1]）
- `metrics`: 附加指标字典
- `passed`: 是否通过正确性检查
- `failure_reason`: 失败原因（可选）

### `get_baseline() -> float`

返回基线分数。用于比较和归一化。通常是最简单的启发式解法的分数。

## 评估模式

### 正确性 + 性能双分

```python
def parse_result(self, result, context):
    if result.return_codes and result.return_codes[0] == 0:
        # 从输出解析性能指标
        output = result.stdout
        time_ms = parse_time(output)
        return EvalOutput(
            score=1.0 / (1.0 + time_ms / 1000),
            metrics={"time_ms": time_ms},
            passed=True,
        )
    return EvalOutput(score=0.0, metrics={}, passed=False, failure_reason="non-zero exit")
```

### 多测试用例

```python
def build_plan(self, candidate, context):
    commands = []
    for test_case in self.test_cases:
        commands.append(CommandSpec(
            argv=["python", "main.py", "--input", test_case.input],
        ))
    return EvaluationPlan(commands=commands)

def parse_result(self, result, context):
    # 所有命令都成功才算通过
    all_ok = all(c == 0 for c in (result.return_codes or []))
    return EvalOutput(
        score=1.0 if all_ok else 0.0,
        metrics={"test_count": len(result.return_codes or [])},
        passed=all_ok,
    )
```

### Progressive Evaluation

```python
def build_plan(self, candidate, context):
    # 阶段 1: 快速冒烟测试
    if context.extra_context.get("stage") == "smoke":
        return EvaluationPlan(
            commands=[CommandSpec(argv=["python", "main.py", "--smoke"])],
            resource_profile="smoke",
        )
    # 阶段 2: 完整测试
    return EvaluationPlan(
        commands=[CommandSpec(argv=["python", "main.py", "--full"])],
        resource_profile="full",
    )
```

## 评估器注册

```python
from omnievolve.eval.evaluator_registry import get_registry

registry = get_registry()
registry.register(MyEvaluator())
```

或通过 CLI 动态加载：

```bash
omnievolve run task.py -e my_module:MyEvaluator -c omnievolve.toml
```

## 注意事项

1. **不能在 `build_plan` 中直接执行代码** — 只能构造声明式计划
2. **`version_id` 必须随评估逻辑变化更新** — 确保评估结果可追溯
3. **`parse_result` 中的分数区间建议 [0, 1]** — 确保与 Beta 回传兼容
4. **`get_baseline` 返回一个合理的下界** — 用于 ROI 计算
5. **多候选共享评估器实例** — evaluator 应该是无状态的
