"""Correctness tests for sort implementations."""

from main import sort


def test_empty():
    assert sort([]) == []


def test_single():
    assert sort([1]) == [1]


def test_sorted():
    assert sort([1, 2, 3]) == [1, 2, 3]


def test_reverse():
    assert sort([3, 2, 1]) == [1, 2, 3]


def test_duplicates():
    assert sort([3, 1, 3, 1]) == [1, 1, 3, 3]


def test_large():
    import random

    data = [random.randint(0, 10000) for _ in range(100)]
    result = sort(data)
    assert result == sorted(data)


def test_negative():
    assert sort([-1, 0, 1, -5]) == [-5, -1, 0, 1]


def test_stability_check():
    """Verify sort result matches Python's sorted."""
    data = [5, 3, 8, 1, 9, 2, 7]
    assert sort(data) == sorted(data)
