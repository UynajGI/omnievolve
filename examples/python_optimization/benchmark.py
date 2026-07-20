"""Benchmark script for sort optimization.

Run by the SortEvaluator's sandbox plan to measure performance.
Outputs JSON: {"speedup": float, "time_ms": float}
"""

import json
import random
import time


def run_benchmark():
    """Run benchmark and output results as JSON."""
    from main import sort

    # Generate test data
    data = [random.randint(0, 10000) for _ in range(1000)]

    # Benchmark candidate sort
    start = time.perf_counter()
    sort(data)
    elapsed = time.perf_counter() - start

    # Baseline: Python's built-in sort
    start_builtin = time.perf_counter()
    sorted(data)
    elapsed_builtin = time.perf_counter() - start_builtin

    speedup = elapsed_builtin / max(elapsed, 1e-9)

    result = {"speedup": speedup, "time_ms": elapsed * 1000}
    print(json.dumps(result))

    # Also write to file for sandbox output collection
    with open("benchmark_result.json", "w") as f:
        json.dump(result, f)


if __name__ == "__main__":
    run_benchmark()
