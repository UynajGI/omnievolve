"""#71 Occam's Circuit —— 种子候选（被 OmniEvolve 进化的对象）。

任务：从多项式级 train 样本恢复隐藏布尔函数，给出**最小且能泛化**的电路。
种子策略（可被进化替换/改进）：
    1. 读 train.csv，推断 n（输入位宽/2）与 m（输出位宽）。
    2. 函数族检测：若 train 全满足 x+y / x*y，则发出对应紧凑电路（行波加法器 /
       移位-相加乘法器）——能完美泛化到 test。
    3. 否则退回 SoP（train 最小项之和）综合——合法但只记忆 train，泛化差。

==== 输出契约（verify_circuit.py 依赖，勿破坏）====
写出 circuit.txt（fanin-2 网表）：
    INPUTS <2n>
    w1 = GATE a b        # GATE in AND OR XOR NAND NOR XNOR；~ 前缀为免费反相
    ...
    OUTPUTS <m 个 wire>  # 顺序即输出位串，LSB-first

==== 进化提示 ====
- 可改：函数族猜测、综合算法（SAT/精确综合、BDD、张量补全、符号回归）、电路最小化。
- 目标：test 精确匹配准确率优先，门数次之（越少越好）。
- mystery 实例函数未知——靠猜测+精确综合，而非记忆 train。
"""

from __future__ import annotations

import csv

TRAIN_FILE = "train.csv"
CIRCUIT_FILE = "circuit.txt"


class Netlist:
    """累积门电路，wire 命名 w1, w2, ...（与验证器一致）。"""

    def __init__(self, n_inputs: int):
        self.n_inputs = n_inputs
        self.lines: list[str] = []
        self._zero: str | None = None

    def gate(self, g: str, a: str, b: str, neg_a: bool = False, neg_b: bool = False) -> str:
        oa = ("~" if neg_a else "") + a
        ob = ("~" if neg_b else "") + b
        name = f"w{len(self.lines) + 1}"
        self.lines.append(f"{name} = {g} {oa} {ob}")
        return name

    def zero(self) -> str:
        if self._zero is None:
            self._zero = self.gate("AND", "x1", "x1", neg_b=True)  # x1 & ~x1 = 0
        return self._zero

    def and_tree(self, wires: list[str]) -> str:
        if not wires:
            return self.zero()
        acc = wires[0]
        for w in wires[1:]:
            acc = self.gate("AND", acc, w)
        return acc

    def or_tree(self, wires: list[str]) -> str:
        if not wires:
            return self.zero()
        acc = wires[0]
        for w in wires[1:]:
            acc = self.gate("OR", acc, w)
        return acc

    def render(self, outputs: list[str]) -> str:
        head = f"INPUTS {self.n_inputs}\n"
        tail = "\nOUTPUTS " + " ".join(outputs) + "\n"
        return head + "\n".join(self.lines) + tail


def _bits_lsb(value: int, width: int) -> list[int]:
    return [(value >> i) & 1 for i in range(width)]


def _from_bits_lsb(bits: list[int]) -> int:
    v = 0
    for i, b in enumerate(bits):
        v |= b << i
    return v


def read_train(path: str):
    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rows.append((row["input"], row["output"]))
    n = len(rows[0][0]) // 2
    m = len(rows[0][1])
    parsed = []
    for inp, out in rows:
        xb = [int(c) for c in inp[:n]]
        yb = [int(c) for c in inp[n:]]
        parsed.append((_from_bits_lsb(xb), _from_bits_lsb(yb), _from_bits_lsb([int(c) for c in out])))
    return n, m, parsed


def detect(parsed, n, m) -> str:
    mask = (1 << m) - 1
    if all(o == ((x + y) & mask) for x, y, o in parsed):
        return "add"
    if all(o == ((x * y) & mask) for x, y, o in parsed):
        return "mul"
    return "unknown"


def xvar(i: int) -> str:
    """x 的第 i 位（0-indexed）对应输入变量 x_{i+1}。"""
    return f"x{i + 1}"


def yvar(i: int, n: int) -> str:
    """y 的第 i 位（0-indexed）对应输入变量 x_{n+i+1}。"""
    return f"x{n + i + 1}"


def build_adder(net: Netlist, n: int) -> list[str]:
    """n 位行波进位加法器，返回 n+1 个和位 wire（LSB-first）。"""
    s0 = net.gate("XOR", xvar(0), yvar(0, n))
    c = net.gate("AND", xvar(0), yvar(0, n))
    sums = [s0]
    for i in range(1, n):
        xi, yi = xvar(i), yvar(i, n)
        t = net.gate("XOR", xi, yi)
        si = net.gate("XOR", t, c)
        m1 = net.gate("AND", xi, yi)
        m2 = net.gate("AND", xi, c)
        m3 = net.gate("AND", yi, c)
        o1 = net.gate("OR", m1, m2)
        c = net.gate("OR", o1, m3)
        sums.append(si)
    sums.append(c)  # 最高位进位
    return sums


def _add_bits(net: Netlist, A: list[str], B: list[str]) -> list[str]:
    """纹波进位加两个 LSB-first 位向量，返回和（长度 max+1）。"""
    L = max(len(A), len(B))
    z = net.zero()
    S: list[str] = []
    carry: str | None = None
    for i in range(L):
        a = A[i] if i < len(A) else z
        b = B[i] if i < len(B) else z
        if carry is None:
            s = net.gate("XOR", a, b)
            carry = net.gate("AND", a, b)
        else:
            t = net.gate("XOR", a, b)
            s = net.gate("XOR", t, carry)
            ab = net.gate("AND", a, b)
            tc = net.gate("AND", t, carry)
            carry = net.gate("OR", ab, tc)
        S.append(s)
    S.append(carry)
    return S


def build_multiplier(net: Netlist, n: int) -> list[str]:
    """n×n 移位-相乘法器，返回 2n 个积位 wire（LSB-first）。"""
    z = net.zero()
    # 部分积 pp[j][i] = x_i AND y_j
    pp = [[net.gate("AND", xvar(i), yvar(j, n)) for i in range(n)] for j in range(n)]
    acc = list(pp[0])  # x * y_0，位于 0..n-1
    for j in range(1, n):
        shifted = [z] * j + pp[j]  # pp[j] 左移 j 位
        acc = _add_bits(net, acc, shifted)
    return acc[: 2 * n]


def build_sop(net: Netlist, n: int, m: int, parsed) -> list[str]:
    """train 最小项之和（记忆 train，合法但泛化差）。"""
    outputs = []
    for b in range(m):
        minterms = []
        for x, y, o in parsed:
            if (o >> b) & 1:
                bits = _bits_lsb(x, n) + _bits_lsb(y, n)
                lits = [(f"x{k + 1}", bit == 0) for k, bit in enumerate(bits)]  # (var, neg)
                minterms.append(_and_literals(net, lits))
        outputs.append(net.or_tree(minterms) if minterms else net.zero())
    return outputs


def _and_literals(net: Netlist, lits: list[tuple[str, bool]]) -> str:
    """AND 一串字面量 (var, neg)；~var 用 NOR(var,var) 实现（计 1 门）。"""
    if not lits:
        return net.zero()
    wires = [net.gate("NOR", v, v) if neg else v for v, neg in lits]
    return net.and_tree(wires)


def run() -> None:
    n, m, parsed = read_train(TRAIN_FILE)
    net = Netlist(n_inputs=2 * n)
    kind = detect(parsed, n, m)
    if kind == "add":
        outputs = build_adder(net, n)
    elif kind == "mul":
        outputs = build_multiplier(net, n)
    else:
        outputs = build_sop(net, n, m, parsed)
    with open(CIRCUIT_FILE, "w", encoding="utf-8") as f:
        f.write(net.render(outputs))
    print(f"Occam seed: detected={kind} n={n} m={m} gates={len(net.lines)}")


if __name__ == "__main__":
    run()
