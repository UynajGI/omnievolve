# Heilbronn Triangle Problem — Initial Code
# Maximize minimum triangle area among 11 points in an equilateral triangle
# Adapted from OpenEvolve alphaevolve_math_problems/heilbronn_triangle

import itertools
import json

import numpy as np

BENCHMARK = 0.036529889880030156
TOL = 1e-6
NUM_POINTS = 11


def heilbronn_triangle11() -> np.ndarray:
    """
    Construct an arrangement of n points on or inside a convex region
    to maximize the area of the smallest triangle formed by these points.
    Here n = 11.

    Returns:
        points: np.ndarray of shape (11,2) with the x,y coordinates.
    """
    n = 11
    points = np.zeros((n, 2))
    return points


def check_inside_triangle_wtol(points: np.ndarray, tol: float = 1e-6):
    for x, y in points:
        cond1 = y >= -tol
        cond2 = np.sqrt(3) * x <= np.sqrt(3) - y + tol
        cond3 = y <= np.sqrt(3) * x + tol
        if not (cond1 and cond2 and cond3):
            raise ValueError(f"Point ({x}, {y}) is outside the equilateral triangle.")


def triangle_area(a: np.ndarray, b: np.ndarray, c: np.ndarray) -> float:
    return np.abs(a[0] * (b[1] - c[1]) + b[0] * (c[1] - a[1]) + c[0] * (a[1] - b[1])) / 2


if __name__ == "__main__":
    points = heilbronn_triangle11()
    check_inside_triangle_wtol(points, TOL)

    a = np.array([0.0, 0.0])
    b = np.array([1.0, 0.0])
    c = np.array([0.5, np.sqrt(3) / 2.0])
    min_area = min(triangle_area(p1, p2, p3) for p1, p2, p3 in itertools.combinations(points, 3))
    min_area_norm = min_area / triangle_area(a, b, c)
    result = {
        "combined_score": float(min_area_norm / BENCHMARK),
        "min_area_normalized": float(min_area_norm),
    }
    print(json.dumps(result))
