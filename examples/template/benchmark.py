"""性能基准测试 — 测量候选代码的执行速度.

输出 JSON 格式的 speedup 指标，供评估器解析。
speedup = 基线时间 / 候选时间（越大越快）
"""

import json
import random
import sys
import time

sys.path.insert(0, "/workspace")

from solution import solve


def baseline_solve(input_data: list[int]) -> int:
    """基线实现 — 用于计算加速比."""
    return sum(x * x for x in input_data if x % 2 == 0)


def main():
    # 生成测试数据（固定种子确保可复现）
    random.seed(42)
    data = [random.randint(0, 10000) for _ in range(50000)]

    # 预热
    solve(data[:100])
    baseline_solve(data[:100])

    # 测量候选代码
    runs = 5
    times = []
    for _ in range(runs):
        start = time.perf_counter()
        result = solve(data)
        times.append(time.perf_counter() - start)

    # 测量基线
    baseline_times = []
    for _ in range(runs):
        start = time.perf_counter()
        ref = baseline_solve(data)
        baseline_times.append(time.perf_counter() - start)

    # 验证正确性
    assert result == ref, f"Incorrect: {result} != {ref}"

    # 计算加速比（取中位数）
    candidate_time = sorted(times)[runs // 2]
    baseline_time = sorted(baseline_times)[runs // 2]
    speedup = baseline_time / max(candidate_time, 1e-9)

    print(json.dumps({
        "speedup": round(speedup, 4),
        "candidate_ms": round(candidate_time * 1000, 3),
        "baseline_ms": round(baseline_time * 1000, 3),
        "correct": True,
    }))


if __name__ == "__main__":
    main()
