"""#34 种子候选：N-queens TN 精确收缩（numpy einsum）。

读取环境变量 NQUEENS_N，构造 N×N 张量网络并精确收缩，
输出 Q(N) 到 candidate_result.json。

这是被 OmniEvolve 进化的对象——进化目标是改进收缩策略
（路径优化、分治、边界 MPS 等），使更大 N 可行。
"""

from __future__ import annotations

import json
import os
import time

import numpy as np


def build_site_tensor() -> np.ndarray:
    """秩-8 格点张量 C（D=2）。"""
    import itertools
    C = np.zeros((2,) * 8, dtype=np.float64)
    for q, ru, rd, cl, cr, d1, d2, d3 in itertools.product([0, 1], repeat=8):
        if q == 0:
            if ru == rd and cl == cr and d1 == d2:
                C[q, ru, rd, cl, cr, d1, d2, d3] = 1.0
        else:
            if ru == 0 and rd == 0 and cl == 0 and cr == 0 and d1 == 0 and d2 == 0:
                C[q, ru, rd, cl, cr, d1, d2, d3] = 1.0
    return C


def contract_nqueens(n: int) -> int:
    """精确收缩 N×N N-queens TN。"""
    from tn_construct import build_nqueens_tn
    expr, operands = build_nqueens_tn(n)

    try:
        import opt_einsum
        result = opt_einsum.contract(expr, *operands, optimize="optimal")
    except ImportError:
        result = np.einsum(expr, *operands, optimize=True)

    return int(round(float(result)))


def main():
    n = int(os.environ.get("NQUEENS_N", "8"))
    t0 = time.time()
    q_n = contract_nqueens(n)
    wall = time.time() - t0

    result = {
        "n": n,
        "q_n": q_n,
        "wall_time_sec": wall,
        "method": "numpy_einsum_optimal",
    }
    with open("candidate_result.json", "w", encoding="utf-8") as f:
        json.dump(result, f)
    print(json.dumps({"status": "ok", "n": n, "q_n": q_n, "wall_sec": round(wall, 3)}))


if __name__ == "__main__":
    main()
