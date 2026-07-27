"""Repeated, deterministic benchmark for sort optimization."""

import json
import random
import time

from omnievolve.eval.benchmark_stats import summarize_samples

REPETITIONS = 15
WARMUP_REPETITIONS = 3
DATA_SIZE = 1_000
BENCHMARK_SEED = 17_291


def _dataset(seed: int) -> list[int]:
    rng = random.Random(seed)
    return [rng.randint(-10_000, 10_000) for _ in range(DATA_SIZE)]


def _time_ms(function, values: list[int]) -> tuple[float, list[int]]:
    start = time.perf_counter_ns()
    result = function(values)
    elapsed_ms = (time.perf_counter_ns() - start) / 1_000_000
    return elapsed_ms, result


def run_benchmark():
    """Run benchmark and output results as JSON."""
    from main import sort

    for index in range(WARMUP_REPETITIONS):
        values = _dataset(BENCHMARK_SEED - index - 1)
        assert sort(values) == sorted(values)

    candidate_samples: list[float] = []
    reference_samples: list[float] = []
    speedup_samples: list[float] = []
    for index in range(REPETITIONS):
        values = _dataset(BENCHMARK_SEED + index)
        expected = sorted(values)
        # Alternate order to reduce systematic thermal/frequency bias.
        if index % 2:
            reference_ms, _ = _time_ms(sorted, values)
            candidate_ms, actual = _time_ms(sort, values)
        else:
            candidate_ms, actual = _time_ms(sort, values)
            reference_ms, _ = _time_ms(sorted, values)
        if actual != expected:
            raise AssertionError(f"candidate returned an incorrect result at repetition {index}")
        candidate_samples.append(candidate_ms)
        reference_samples.append(reference_ms)
        speedup_samples.append(reference_ms / max(candidate_ms, 1e-12))

    candidate = summarize_samples(candidate_samples, seed=BENCHMARK_SEED)
    reference = summarize_samples(reference_samples, seed=BENCHMARK_SEED + 1)
    speedup = summarize_samples(speedup_samples, seed=BENCHMARK_SEED + 2)
    result = {
        "benchmark_schema_version": 1,
        "seed": BENCHMARK_SEED,
        "repetitions": REPETITIONS,
        # Backwards-compatible scalar fields use robust medians.
        "speedup": speedup.median,
        "speedup_ci_low": speedup.ci_low,
        "speedup_ci_high": speedup.ci_high,
        "time_ms": candidate.median,
        "candidate_ms": candidate.to_dict(),
        "reference_ms": reference.to_dict(),
        "speedup_stats": speedup.to_dict(),
    }
    encoded = json.dumps(result, sort_keys=True)
    print(encoded)
    with open("benchmark_result.json", "w", encoding="utf-8") as handle:
        handle.write(encoded)


if __name__ == "__main__":
    run_benchmark()
