"""#127 收缩代价检查器（沙箱内运行，不可作弊核心）。

给定一个 einsum 表达式 + 索引维度 + 候选收缩树（有序对列表），
用精确整数算术重算 FLOPs 和峰值内存。绝不信任候选自报的代价。

收缩树格式（candidate_result.json 中的 "contraction_tree"）：
    [[0, 1], [2, 3], [4, 5]]  — 每步收缩的两个操作数编号（按当前可用张量编号）

代价模型（标准 cotengra 约定）：
    - 每步 FLOPs = prod(所有参与索引的维度)（含被收缩的索引）
    - 结果张量大小 = prod(保留索引的维度)
    - 峰值内存 = 过程中同时存在的张量大小的最大值（字节，float64）

输出 JSON：
    {"flops": int, "peak_memory_bytes": int, "valid": bool, "error": str}
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path


def compute_contraction_cost(
    indices_per_tensor: list[set[str]],
    dim_map: dict[str, int],
    tree: list[list[int]],
) -> dict:
    """从收缩树重算 FLOPs 和峰值内存。

    Args:
        indices_per_tensor: 每个初始张量的索引集合
        dim_map: 索引 -> 维度
        tree: 收缩树，每步 [i, j] 表示收缩当前编号 i 和 j 的张量

    Returns:
        {"flops": int, "peak_memory_bytes": int, "valid": bool, "error": str}
    """
    n = len(indices_per_tensor)
    if n < 2:
        return {"flops": 0, "peak_memory_bytes": 0, "valid": True, "error": ""}

    # 验证树结构
    if len(tree) != n - 1:
        return {
            "flops": 0, "peak_memory_bytes": 0, "valid": False,
            "error": f"tree has {len(tree)} steps, expected {n - 1}",
        }

    # 当前可用张量的索引集合（按编号）
    available: list[set[str] | None] = [set(s) for s in indices_per_tensor]
    total_flops = 0
    # 初始内存：所有初始张量
    current_memory = sum(
        math.prod(dim_map[ix] for ix in s) for s in available
    )
    peak_memory = current_memory

    for step, pair in enumerate(tree):
        if len(pair) != 2:
            return {
                "flops": 0, "peak_memory_bytes": 0, "valid": False,
                "error": f"step {step}: pair must have 2 elements",
            }
        i, j = pair
        if i < 0 or i >= len(available) or available[i] is None:
            return {
                "flops": 0, "peak_memory_bytes": 0, "valid": False,
                "error": f"step {step}: operand {i} not available",
            }
        if j < 0 or j >= len(available) or available[j] is None:
            return {
                "flops": 0, "peak_memory_bytes": 0, "valid": False,
                "error": f"step {step}: operand {j} not available",
            }
        if i == j:
            return {
                "flops": 0, "peak_memory_bytes": 0, "valid": False,
                "error": f"step {step}: cannot contract tensor with itself",
            }

        idx_i = available[i]
        idx_j = available[j]

        # 收缩索引 = 交集（不再被后续张量使用的）
        # 简化：交集即为被收缩的索引（标准二元收缩）
        contracted = idx_i & idx_j
        result_idx = (idx_i | idx_j) - contracted

        # FLOPs = prod(所有参与索引的维度)
        all_indices = idx_i | idx_j
        step_flops = math.prod(dim_map[ix] for ix in all_indices)
        total_flops += step_flops

        # 结果张量大小
        result_size = math.prod(dim_map[ix] for ix in result_idx) if result_idx else 1

        # 更新内存：移除两个操作数，加入结果
        size_i = math.prod(dim_map[ix] for ix in idx_i) if idx_i else 1
        size_j = math.prod(dim_map[ix] for ix in idx_j) if idx_j else 1
        current_memory = current_memory - size_i - size_j + result_size
        peak_memory = max(peak_memory, current_memory)

        # 标记已用，追加结果
        available[i] = None
        available[j] = None
        available.append(result_idx)

    # 验证最终只剩一个张量
    remaining = [s for s in available if s is not None]
    if len(remaining) != 1:
        return {
            "flops": 0, "peak_memory_bytes": 0, "valid": False,
            "error": f"after contraction, {len(remaining)} tensors remain (expected 1)",
        }

    return {
        "flops": total_flops,
        "peak_memory_bytes": peak_memory * 8,  # float64
        "valid": True,
        "error": "",
    }


def load_instance(path: str | Path) -> tuple[list[set[str]], dict[str, int]]:
    """加载实例 JSON -> (indices_per_tensor, dim_map)。"""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    indices_per_tensor = [set(t) for t in data["tensors"]]
    dim_map = data["dimensions"]
    return indices_per_tensor, dim_map


if __name__ == "__main__":
    # 从 candidate_result.json 读取候选收缩树，从 instance.json 读取实例
    instance_path = sys.argv[1] if len(sys.argv) > 1 else "instance.json"
    candidate_path = "candidate_result.json"

    try:
        indices_per_tensor, dim_map = load_instance(instance_path)
    except (OSError, json.JSONDecodeError, KeyError) as exc:
        print(json.dumps({"flops": 0, "peak_memory_bytes": 0, "valid": False, "error": f"bad instance: {exc}"}))
        sys.exit(0)

    try:
        with open(candidate_path, encoding="utf-8") as f:
            cand = json.load(f)
        tree = cand["contraction_tree"]
    except (OSError, json.JSONDecodeError, KeyError) as exc:
        print(json.dumps({"flops": 0, "peak_memory_bytes": 0, "valid": False, "error": f"bad candidate: {exc}"}))
        sys.exit(0)

    result = compute_contraction_cost(indices_per_tensor, dim_map, tree)
    print(json.dumps(result))
