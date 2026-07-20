"""Circle Packing 初始代码.

目标：在单位正方形内放置 N 个不重叠的圆，最大化最小半径。
这是一个经典几何优化问题，验证 OmniEvolve 在约束优化上的效果。
"""


def pack_circles(
    num_circles: int, positions: list[tuple[float, float]], radii: list[float]
) -> float:
    """计算最小半径（越小 = 越差）。返回 -min_radius 作为目标函数值（越大越好）."""
    import math

    min_radius = float("inf")
    for i in range(num_circles):
        x_i, y_i = positions[i]
        # 边界约束
        r_max = min(x_i, 1.0 - x_i, y_i, 1.0 - y_i)
        min_radius = min(min_radius, r_max)
        for j in range(i + 1, num_circles):
            x_j, y_j = positions[j]
            dist = math.hypot(x_i - x_j, y_i - y_j)
            min_radius = min(min_radius, dist - radii[j])

    return -min_radius  # 负值 => 进化最大化


def solve() -> float:
    """进化入口：返回 fitness（越大越好）."""
    # 基线：简单的网格排列
    import math

    n = 9
    side = int(math.sqrt(n))
    radius = 0.5 / side * 0.9
    positions = [
        (radius + (i % side) * 2 * radius, radius + (i // side) * 2 * radius) for i in range(n)
    ]
    radii = [radius] * n
    return pack_circles(n, positions, radii)
