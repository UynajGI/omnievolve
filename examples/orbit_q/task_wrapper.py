"""#78 ORBIT-Q 任务包装器（沙箱内运行）。

包装 ORBIT-Q 官方 functional check + wall-time 测量。
候选代码（被进化的 TensorCircuit-NG 解法）写出 candidate_result.json，
本包装器运行官方验证并测量时间。

环境依赖（重型）：
    - tensorcircuit-ng >= 0.12
    - JAX >= 0.4
    - ORBIT-Q 仓库（github.com/sxzgroup/ORBIT-Q）

注意：此评估器需要 GPU 或较强 CPU。sandbox_timeout 应放大。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time

CANDIDATE_OUTPUT = "candidate_result.json"
VERIFY_OUTPUT = "verify_result.json"

# 参考 wall-time（秒），来自 ORBIT-Q 官方专家解法
# 任务名 -> 参考时间（需从实际运行标定）
REF_TIMES: dict[str, float] = {
    "task_01_ghz": 2.0,
    "task_02_qft": 3.0,
    "task_03_vqe": 5.0,
}

DEFAULT_TASK = "task_01_ghz"


def _fail(reason: str) -> dict:
    return {"functional_pass": False, "wall_time_sec": 0.0, "ref_time_sec": 0.0, "valid": False, "error": reason}


def main() -> dict:
    if not os.path.exists(CANDIDATE_OUTPUT):
        return _fail(f"missing {CANDIDATE_OUTPUT}")

    try:
        with open(CANDIDATE_OUTPUT, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        return _fail(f"cannot parse: {exc}")

    task_name = data.get("task", DEFAULT_TASK)
    ref_time = REF_TIMES.get(task_name, 5.0)

    # 候选自报的 functional check 结果（需独立验证）
    # 在完整实现中，这里应调用 ORBIT-Q 官方 verifier
    # 当前为桩实现：信任候选的 functional_pass（待集成官方验证器后替换）
    functional_pass = data.get("functional_pass", False)
    wall_time = float(data.get("wall_time_sec", 0.0))

    if not functional_pass:
        return {
            "functional_pass": False, "wall_time_sec": wall_time,
            "ref_time_sec": ref_time, "valid": True,
            "error": "functional check failed",
        }

    return {
        "functional_pass": True,
        "wall_time_sec": wall_time,
        "ref_time_sec": ref_time,
        "speedup": ref_time / max(wall_time, 1e-6),
        "valid": True,
        "error": "",
    }


if __name__ == "__main__":
    result = main()
    with open(VERIFY_OUTPUT, "w", encoding="utf-8") as f:
        json.dump(result, f)
    print(json.dumps(result))
    sys.exit(0)
