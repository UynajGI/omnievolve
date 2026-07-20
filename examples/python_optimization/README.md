# Python 排序优化示例

这个示例展示如何使用 OmniEvolve 优化一个排序算法。

## 文件说明

- `initial_code.py` — 初始实现（冒泡排序，故意写慢）
- `test_sort.py` — 正确性测试（OmniEvolve 必须保持通过）
- `evaluator.py` — TaskEvaluator 实现（正确性门 + 性能评分）

## 运行

```bash
# 在 examples/python_optimization 目录下
cd examples/python_optimization

# 使用 OmniEvolve 优化
omnievolve run ./initial_code.py \
    --evaluator evaluator:SortEvaluator \
    --config ../../configs/omnievolve.toml.example \
    --trusted \
    --gens 10
```

## 评估逻辑

Score = 0.5 (correctness baseline) + 0.5 × min(speedup/10, 1.0)

- 正确性是硬门：测试不通过 → score = 0
- 性能是软分：speedup 相对 Python 内置 sort 的比率
- 10x 加速 → 满分

## 预期进化方向

OmniEvolve 应能发现：
1. 快速排序（quicksort）
2. 归并排序（mergesort）
3. Python 内置 `sorted()` 或 `list.sort()`
4. 计数排序（对整数特化）
