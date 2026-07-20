"""Initial sort implementation — bubble sort.

OmniEvolve 会尝试优化这个函数。目标是找到更快且正确的排序实现。
"""


def sort(arr: list[int]) -> list[int]:
    """Sort an array using bubble sort.

    This is intentionally slow — the evolution engine should discover
    faster algorithms (quicksort, mergesort, timsort, etc.)
    """
    result = arr[:]
    n = len(result)
    for i in range(n):
        for j in range(0, n - i - 1):
            if result[j] > result[j + 1]:
                result[j], result[j + 1] = result[j + 1], result[j]
    return result


if __name__ == "__main__":
    import json
    import random
    import time

    # Benchmark
    data = [random.randint(0, 10000) for _ in range(1000)]
    start = time.perf_counter()
    sort(data)
    elapsed = time.perf_counter() - start

    # Baseline: Python's built-in sort
    start_builtin = time.perf_counter()
    sorted(data)
    elapsed_builtin = time.perf_counter() - start_builtin

    speedup = elapsed_builtin / max(elapsed, 1e-9)
    print(json.dumps({"speedup": speedup, "time_ms": elapsed * 1000}))
