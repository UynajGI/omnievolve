"""#127 种子候选：贪心收缩顺序搜索。

读取 instance.json（张量网络定义），用贪心策略（每步选 FLOPs 最小的收缩对）
生成收缩树，写出 candidate_result.json。

这是被 OmniEvolve 进化的对象——进化目标是改进搜索策略（如模拟退火、
随机重启、超图分区等），找到比贪心更便宜的收缩顺序。
"""

from __future__ import annotations

import json
import math
import sys


def load_instance(path: str) -> tuple[list[set[str]], dict[str, int]]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return [set(t) for t in data["tensors"]], data["dimensions"]


def contraction_flops(idx_a: set[str], idx_b: set[str], dim_map: dict[str, int]) -> int:
    """计算收缩两个张量的 FLOPs。"""
    all_idx = idx_a | idx_b
    return math.prod(dim_map[ix] for ix in all_idx)


def greedy_search(indices_per_tensor: list[set[str]], dim_map: dict[str, int]) -> list[list[int]]:
    """贪心收缩：每步选 FLOPs 最小的可收缩对。"""
    n = len(indices_per_tensor)
    available: list[set[str] | None] = [set(s) for s in indices_per_tensor]
    tree: list[list[int]] = []

    for _ in range(n - 1):
        best_pair = None
        best_cost = float("inf")

        # 枚举所有可用对
        active = [i for i, s in enumerate(available) if s is not None]
        for ai in range(len(active)):
            for bi in range(ai + 1, len(active)):
                i, j = active[ai], active[bi]
                cost = contraction_flops(available[i], available[j], dim_map)
                if cost < best_cost:
                    best_cost = cost
                    best_pair = (i, j)

        if best_pair is None:
            break

        i, j = best_pair
        idx_i = available[i]
        idx_j = available[j]
        contracted = idx_i & idx_j
        result_idx = (idx_i | idx_j) - contracted

        tree.append([i, j])
        available[i] = None
        available[j] = None
        available.append(result_idx)

    return tree


def main():
    instance_path = "instance.json"
    indices_per_tensor, dim_map = load_instance(instance_path)
    tree = greedy_search(indices_per_tensor, dim_map)

    result = {"contraction_tree": tree}
    with open("candidate_result.json", "w", encoding="utf-8") as f:
        json.dump(result, f)
    print(json.dumps({"status": "ok", "tree_steps": len(tree)}))


if __name__ == "__main__":
    main()
