"""初始代码 — 你的待优化函数.

OmniEvolve 会进化这个文件中的代码。
把你的初始实现放在这里，引擎会尝试找到更好的版本。

要求:
- 至少包含一个可被评估的函数
- 函数签名在进化过程中保持不变（评估器依赖它）
- 可以包含辅助函数和类
"""


def solve(input_data: list[int]) -> int:
    """你的核心函数 — 替换为实际任务.

    示例：计算列表中所有偶数的平方和（故意用低效实现）。
    OmniEvolve 会尝试优化这个函数。

    Args:
        input_data: 输入数据

    Returns:
        计算结果
    """
    # 故意低效的实现 — 引擎应该发现更快的方式
    result = 0
    for i in range(len(input_data)):
        if input_data[i] % 2 == 0:
            result += input_data[i] * input_data[i]
    return result


# ═══════════════════════════════════════════
# 以下为评估辅助代码（benchmark 入口）
# ═══════════════════════════════════════════

if __name__ == "__main__":
    import json
    import random
    import time

    # 生成测试数据
    data = [random.randint(0, 10000) for _ in range(10000)]

    # 计时
    start = time.perf_counter()
    result = solve(data)
    elapsed = time.perf_counter() - start

    # 基线对比（Python 内置方式）
    start_ref = time.perf_counter()
    ref = sum(x * x for x in data if x % 2 == 0)
    elapsed_ref = time.perf_counter() - start_ref

    speedup = elapsed_ref / max(elapsed, 1e-9)
    correct = result == ref

    print(json.dumps({
        "speedup": round(speedup, 4),
        "time_ms": round(elapsed * 1000, 3),
        "correct": correct,
        "result": result,
    }))
