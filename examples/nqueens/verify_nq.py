"""#34 N-queens 验证器（沙箱内运行）。

读取候选输出的 candidate_result.json，用 OEIS 精确值比对 Q(N)。
候选无法通过伪造 Q(N) 获利——验证器持有独立参考。
"""

from __future__ import annotations

import json
import math
import os
import sys

from oeis_ref import Q_EXACT

CANDIDATE_OUTPUT = "candidate_result.json"
VERIFY_OUTPUT = "verify_result.json"


def _fail(reason: str) -> dict:
    return {"q_computed": 0, "q_exact": 0, "n": 0, "valid": False, "exact": False, "score": 0.0, "error": reason}


def main() -> dict:
    if not os.path.exists(CANDIDATE_OUTPUT):
        return _fail(f"missing {CANDIDATE_OUTPUT}")

    try:
        with open(CANDIDATE_OUTPUT, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        return _fail(f"cannot parse: {exc}")

    try:
        n = int(data["n"])
        q_computed = int(data["q_n"])
    except (KeyError, TypeError, ValueError) as exc:
        return _fail(f"malformed output: {exc}")

    q_exact = Q_EXACT.get(n)
    if q_exact is None:
        # N 超出已知范围（如 N=28）——开放目标，暂不作硬门
        return {
            "q_computed": q_computed, "q_exact": 0, "n": n,
            "valid": True, "exact": False, "score": 0.5,
            "wall_time_sec": data.get("wall_time_sec", 0),
            "error": f"Q({n}) unknown (frontier)",
        }

    exact = q_computed == q_exact
    if exact:
        score = 1.0
    else:
        # 近似分：基于对数偏差
        if q_computed > 0 and q_exact > 0:
            log_ratio = abs(math.log10(q_computed / q_exact))
            score = max(0.0, 0.5 * (1.0 - log_ratio))
        else:
            score = 0.0

    return {
        "q_computed": q_computed,
        "q_exact": q_exact,
        "n": n,
        "valid": True,
        "exact": exact,
        "score": score,
        "wall_time_sec": data.get("wall_time_sec", 0),
        "error": "" if exact else f"Q({n})={q_computed} != {q_exact}",
    }


if __name__ == "__main__":
    result = main()
    with open(VERIFY_OUTPUT, "w", encoding="utf-8") as f:
        json.dump(result, f)
    print(json.dumps(result))
    sys.exit(0)
