# 健康指标：公式、假设与限制

S8-18: 健康指标解释文档

## 概述

OmniEvolve 使用双轨评估：
- **轨道 A（任务评估器）**：用户定义，评估候选代码的任务分数
- **轨道 B（系统健康度）**：框架内置，评估搜索过程本身的效率

轨道 B 的指标通过 `TelemetryAggregator` 计算客观、可复现的数值，不调用 LLM 做主观打分。

## 指标定义

### 1. ROI（成本归一化投资回报率）

**公式：**
```
ROI = ΔHV / (λ₁·C_API + λ₂·C_compute + λ₃·T_wall)
```

- `ΔHV`：Pareto 前沿提升（多目标）或 best-score improvement（单目标）
- `C_API`：API 费用（USD）
- `C_compute`：计算时间（秒）
- `T_wall`：墙钟时间（秒）
- `λ₁=1.0, λ₂=0.1, λ₃=0.01`（可配置）

**假设：**
- 成本是可计量的（API 返回 token 数和费用）
- 前沿提升定义为窗口内 max(scores) - min(scores)

**限制：**
- 不区分"有价值的前沿提升"和"噪声驱动的分数波动"
- 成本权重是经验值，不同任务可能需要调整
- 反事实无法计算（不知道"如果用其他策略会怎样"）

### 2. 覆盖率（搜索空间覆盖熵）

**公式：**
```
coverage_entropy = 0.30 × H(thought_clusters)
                 + 0.25 × CV(knn_distances)
                 + 0.25 × |unique_AST_features| / 100
                 + 0.20 × H(branch_sizes)
```

- `H(·)`：归一化 Shannon 熵
- `CV`：变异系数（标准差/均值）
- 权重为经验默认值

**假设：**
- 思想簇的分布反映搜索方向多样性
- KNN 距离分布反映候选代码的语义分散度
- AST 特征覆盖反映代码结构多样性

**限制：**
- 簇分配依赖 embedding 质量
- AST 特征提取是简化的（只统计节点类型）
- 不捕获"有意义的覆盖"vs"随机噪声覆盖"

### 3. 记忆有效性

**公式：**
```
memory_effectiveness = 0.30 × citation_rate
                     + 0.40 × adoption_rate
                     + 0.30 × duplicate_reduction
```

- `citation_rate`：检索的记忆被引用的比例
- `adoption_rate`：检索的记忆被采用（影响候选）的比例
- `duplicate_reduction`：重复尝试减少率

**假设：**
- 引用和采用是可追踪的（Agent 显式记录）
- 减少重复尝试 = 记忆有效阻止了重复探索

**限制：**
- "采用"的定义模糊（何时算记忆影响了决策？）
- 无记忆基线无法直接计算 duplicate_reduction（需消融实验）

### 4. 上下文污染度

**公式：**
```
pollution_ratio = 0.40 × semantic_duplicate_ratio
                + 0.35 × unused_retrieval_ratio
                + 0.25 × stale_memory_ratio
```

**假设：**
- 语义重复 = embedding 相似度 > 0.95 的上下文项
- 未使用 = 检索后未被 Agent 引用
- 过时 = 超过 N 代未被引用的记忆

**限制：**
- "未使用"需要 Agent 显式标记（可能遗漏）
- 阈值 0.95 是经验值
- 不区分"有害污染"和"无害冗余"

## HealthPolicy 规则与迟滞

| 指标 | WARN 条件 | CRITICAL 条件 | 触发动作 |
|------|-----------|---------------|----------|
| ROI | < 0.001 | — | 触发 MetaPlanner |
| coverage_entropy | < 0.35 | — | 建议增加探索 |
| success_rate | — | < 0.30 | 检查 evaluator/sandbox 配置 |
| pollution_ratio | > 0.30 | — | 建议剪枝旧记忆 |
| stagnation | 连续 3 窗口 ΔHV ≤ 0.001 | — | 触发 MetaPlanner |

**迟滞机制：** 停滞检测需要连续 N 个窗口（默认 3），避免单代偶然波动触发误报。

## 不可用场景

1. **候选数 < 5**：统计指标不稳定，不触发 MetaPlanner
2. **评估器有噪声**：高方差的评估器会使 ROI 和覆盖率指标失真
3. **无 API 费用数据**：ROI 的 C_API 分量无法计算
4. **单目标 vs 多目标**：ΔHV 定义不同（单目标用 best-score，多目标用 Pareto hypervolume）

## 指标绑定策略窗口

所有轨道 B 指标绑定到 **SearchPolicyVersion** 和 **时间窗口**（`health_window_gens`），
不绑定到单个候选。这确保指标反映搜索过程质量，而非单个候选的运气。
