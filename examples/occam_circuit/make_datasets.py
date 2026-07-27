"""生成 #71 Occam's Circuit 的 practice 数据集（自包含，免下载官方 release）。

编码（与题面一致）：
- 输入 = 2n 个字符：先 x 的 n 位，再 y 的 n 位，均 LSB-first（块内第 i 个字符是第 i-1 位）。
- 输出 = m 个字符，LSB-first。

practice 实例真值公开（addition / multiplication），用于验证 OmniEvolve 闭环。
正式 mystery 实例（函数隐藏、SHA 锁定）需官方 release 数据；此处仅 practice。

用法: python make_datasets.py
生成: datasets/practice-add-n4/{train.csv,test_inputs.csv,test_outputs.csv}
      datasets/practice-mul-n4/{...}
"""

from __future__ import annotations

import csv
from pathlib import Path

import numpy as np

HERE = Path(__file__).parent
DATASETS = HERE / "datasets"


def to_bits_lsb(value: int, width: int) -> str:
    """整数 -> LSB-first 位串（字符 i 是第 i 位）。"""
    return "".join(str((value >> i) & 1) for i in range(width))


def make_input(x: int, y: int, n: int) -> str:
    """输入位串：x 的 n 位（LSB-first）拼接 y 的 n 位（LSB-first）。"""
    return to_bits_lsb(x, n) + to_bits_lsb(y, n)


def gen_instance(name: str, n: int, m: int, fn, seed: int, n_train: int) -> None:
    """枚举全部 2^(2n) 个输入，确定性切分 train/test，写出 CSV。"""
    rng = np.random.default_rng(seed)
    pairs = [(x, y) for x in range(2 ** n) for y in range(2 ** n)]
    idx = rng.permutation(len(pairs))
    train_idx = set(idx[:n_train].tolist())

    out_dir = DATASETS / name
    out_dir.mkdir(parents=True, exist_ok=True)

    train_rows, test_in_rows, test_out_rows = [], [], []
    for i, (x, y) in enumerate(pairs):
        inp = make_input(x, y, n)
        out = to_bits_lsb(int(fn(x, y)), m)
        if i in train_idx:
            train_rows.append((inp, out))
        else:
            test_in_rows.append(inp)
            test_out_rows.append(out)

    with open(out_dir / "train.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["input", "output"])
        w.writerows(train_rows)
    with open(out_dir / "test_inputs.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["input"])
        for r in test_in_rows:
            w.writerow([r])
    with open(out_dir / "test_outputs.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["output"])
        for r in test_out_rows:
            w.writerow([r])

    print(f"{name}: 2n={2 * n} m={m} train={len(train_rows)} test={len(test_in_rows)} -> {out_dir}")


def main() -> None:
    # practice-add-n4: x+y, n=4, m=5 (x,y<16 -> sum<32)
    gen_instance("practice-add-n4", n=4, m=5, fn=lambda x, y: x + y, seed=11, n_train=120)
    # practice-mul-n4: x*y, n=4, m=8 (x,y<16 -> prod<256)
    gen_instance("practice-mul-n4", n=4, m=8, fn=lambda x, y: x * y, seed=11, n_train=120)


if __name__ == "__main__":
    main()
