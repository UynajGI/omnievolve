# OmniEvolve v0.2 — 剩余实施计划

> 2026-07-20
> 基于设计文档 vs 实际状态、AlphaEvolve/MLEvolve 对比分析的最终计划

## 已完成（本次会话吸收的外部论文）

| 来源 | 特性 | 实现 |
|------|------|------|
| AlphaEvolve | SEARCH/REPLACE diff 格式 | `engine/diff.py` + Coder prompt |
| AlphaEvolve | EVOLVE-BLOCK 标记 | `engine/diff.py`: parse_evolve_blocks() |
| AlphaEvolve | Rich prompt（多历史程序+分数） | Coder._build_user_message: inspiration programs |
| AlphaEvolve | 元 prompt 进化 | PromptEvolver → MetaPlanner → evolve_prompt action |
| MLEvolve | 渐进式 MCGS（已内化） | Beta 回传 + UCB/PUCT + 虚拟损失 |
| - | 分层记忆 L0-L4 | MemoryStore + memory_entry 表 |

## 计划项（设计文档要求但未实现）

### P0: Reference edges — 跨分支信息流

**现状**: `candidate_reference_edge` 表已建（schema.sql），但从未写入。
**目标**: expansion 时写入跨分支引用边，启用 GraphStore 导出完整 DAG。

**实现路径**:
1. `EvolutionEngine._evolve_one`: 候选生成后，写入 reference edge
   - `reference_type = "cross_branch"` 当 inspiration 来自其他 island
   - `reference_type = "memory"` 当使用了 retrieval 结果
   - `reference_type = "crossover_hint"` 当 crossover 融合了多父代
2. `GraphStore.load_subgraph`: 同时加载 `candidate_lineage`（主边）和 `candidate_reference_edge`（引用边）
3. `omnievolve export` 命令导出完整 DAG（含两种边类型）

**预期效果**: GraphML 导出包含完整的图结构，不再是平铺节点。

### P1: Progressive exploration schedule

**现状**: MCTS 使用固定的 `exploration` 参数（默认 1.414）。
**目标**: exploration 常数随时间衰减，搜索后期从探索转向利用。

**实现路径**:
1. `ProgressiveMCGS.__init__`: 新增 `schedule: str = "constant" | "progressive"` 参数
2. Progressive schedule:
   ```python
   # c(t) = c_max - (c_max - c_min) * (t / t_max)
   # 或 piecewise: [探索期, 过渡期, 利用期]
   ```
3. `EvolutionEngine._evolve_one`: 每代传入当前时间进度 `t/t_max`
4. 配置项: `[mcts] schedule = "progressive"`, `c_min = 0.2`

**预期效果**: 后期搜索集中在高分分支，避免浪费 token 在低分候选上。

## 不实施（有替代方案或不属于设计范围）

| 特性 | 不实施理由 |
|------|-----------|
| Stepwise 模块化生成 | SEARCH/REPLACE + EVOLVE-BLOCK 已覆盖多模块场景；LLM 收到完整父代码后可自主选择改哪个模块 |
| Domain Knowledge Base | Evaluator 的 `build_plan`/`get_baseline` 已封装领域知识；静态 KB 增加维护成本且不跨域通用 |
| Adaptive mode selection | Coder._parse_response 已有 3 级 fallback: SEARCH/REPLACE → JSON → code block → raw |

## 现状总结

```
已实施总数:
  测试: 514 tests, 75% coverage
  后端: 4 种 sandbox (TrustedSubprocess/Docker/Monty/Hardened)
  搜索: Beta MCTS + UCB/PUCT
  代码: SEARCH/REPLACE diff + EVOLVE-BLOCK
  记忆: 分层 L0-L4 + vector outbox
  策略: BayesianTuner (GP+EI) + PromptEvolver
  评估: 轨A 任务评估 + 轨B 健康度
  安全: Governance L0/L1/L2 + Champion-Challenger

待实施:
  P0: Reference edges（跨分支信息流）
  P1: Progressive exploration schedule（探索→利用衰减）
```
