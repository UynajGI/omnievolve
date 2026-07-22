"""正确性测试 — 验证候选代码的 solve() 函数.

这个文件会被挂载到沙箱中运行。
候选代码以 solution.py 的形式存在于 /workspace/ 目录。

修改指南:
- 添加更多测试用例覆盖边界情况
- 确保测试能验证核心正确性（不要测试实现细节）
- 测试应该在 10 秒内完成
"""

import random
import sys

sys.path.insert(0, "/workspace")

from solution import solve


def test_basic():
    """基本功能测试."""
    assert solve([1, 2, 3, 4, 5]) == sum(x * x for x in [1, 2, 3, 4, 5] if x % 2 == 0)


def test_empty():
    """空列表."""
    assert solve([]) == 0


def test_no_even():
    """无偶数."""
    assert solve([1, 3, 5, 7]) == 0


def test_all_even():
    """全偶数."""
    assert solve([2, 4, 6]) == 4 + 16 + 36


def test_negative():
    """负数."""
    assert solve([-2, -3, 4]) == 4 + 16


def test_large():
    """大列表（性能 + 正确性）."""
    data = [random.randint(-10000, 10000) for _ in range(5000)]
    expected = sum(x * x for x in data if x % 2 == 0)
    assert solve(data) == expected


def test_zeros():
    """包含零."""
    assert solve([0, 1, 2, 0, 3]) == 0 + 4 + 0
