# OmniEvolve v0.2 → v0.3 优化计划

> 基于：设计文档 v0.2 差距分析 + OpenEvolve/MLEvolve 工程对比 + 全流程端到端测试发现

---

## 一、差距总览

### 1.1 设计文档 vs 实现（MCGS 层面）

| 设计文档要求 | 当前实现 | 差距 |
|-------------|---------|------|
| `mcts.py` 标注为"渐进式 MCGS / 可选 MCTS" | 固定 UCB1，无探索衰减 | ❌ 未实现 |
| 探索-利用软切换（w(t) 从 1.0 衰减到 w_min） | 无软切换机制 | ❌ 未实现 |
| 分段衰减 C(t) 探索常数 | 固定 C=1.414 | ❌ 未实现 |
| 强制反向传播（后期加速收敛 + 多样性） | 无 | ❌ 未实现 |
| Top-K 加权随机利用 | 无 | ❌ 未实现 |
| 跨分支融合 FusionAgent | InspirationCollector 只做引用，不做合并 | 部分 |
| 基于停滞检测的动作升级（improve → evolution → fusion） | 无分层升级 | ❌ 未实现 |

### 1.2 设计文档 vs 实现（Prompt 层面）

| 设计文档要求 | 当前实现 | 差距 |
|-------------|---------|------|
| Director 按 L0~L4 scope 混合检索 memory | 按 success_only 检索，200 字符摘要 | 语义缩水 |
| Director 加载父代、兄弟和引用分支摘要 | 只加载父代 thoughts | ❌ 缺兄弟/引用分支 |
| Coder 获得父代 + inspiration programs + eval 历史 | 获得父代码 + top-3 高分 + 200 字符记忆 | ❌ 缺 eval 错误反馈 |
| Critic 静态审查（语法、补丁可应用性、静态逻辑） | 只做 ast.parse + 模式匹配 + LLM 审查 | ❌ 缺补丁可应用性检查 |

### 1.3 有效反馈闭环（研究对比发现）

| 能力 | MLEvolve | OpenEvolve | OmniEvolve |
|------|----------|-----------|-------------|
| debug_agent 获取沙箱 stderr | ✅ | ✅ (artifact side-channel) | ❌ |
| 评估失败信息回流到 Coder | ✅ | ✅ | ❌ ⚠️ 主线阻塞器 |
| 代码审查基于真实执行反馈 | ✅ | 不适用 | ❌（Critic 只做静态） |
| 全局记忆 BM25+FAISS 混合检索 | ✅ | 不适用 | FTS5+Vector（等同） |
| 多模式代码生成（基础/分步/diff） | ✅ | 不适用 | 单路径 diff |

### 1.4 端到端测试暴露的问题

| 问题 | 影响 | 根因 |
|------|------|------|
| 第 2 代起候选全部 0 分（sort 测试 19% 通过率） | 进化无效 | Coder 得不到失败原因 |
| 同等任务换个 seed 结果天差地别（heilbronn 0.5814→0.0179） | 不可复现 | 搜索策略无韧性 |
| Critic "passed" 但代码仍通不过 pytest | 假阳性 | Critic 看不到沙箱结果 |
| 模型慢调用（60s+）无超时回退 | 进程卡死 | 无 per-model timeout/fallback |

---

## 二、优化路线（按投入产出比排序）

### 🔴 P0 — 阻塞主线（1-2 天）

#### P0-1: 评估失败反馈闭环

**现状**: `EvalOutput.failure_reason` 和 `stderr` 已存入 DB（`evaluation_run.metrics` 和 `artifact.stderr_hash`），但 `AgentContext` 不含失败上下文。Coder 只知道 score=0，不知道为何为 0。

**改动**:
1. `fast_loop.py`: 从 `evaluation_run` 取 parent 的 `stderr_hash` → 读 stderr 内容 → 注入 `AgentContext.last_eval_failure`
2. `coder.py` `_build_user_message()`: 新增 `## Previous Evaluation Failure` 区块（含 stderr 后 500 字）
3. `AgentContext` 新增字段: `last_eval_failure: str = ""`

**预期效果**: 第 2 代及以后候选通过率从 19% 提升到 40-60%

#### P0-2: Critic 沙箱反馈增强

**现状**: Critic 只做 `ast.parse` + 危险模式检测 + LLM 审查。看不到真实执行结果。

**改动**:
1. `fast_loop.py`: Critic.review() 前，从上一个 eval 加载 stderr/失败信息
2. `critic.py`: 新增 `review_with_execution_result()` 方法，接收 `last_eval_stderr: str`
3. 当上一轮失败时，Critic 检查：a) 代码是否正确处理了上次报错？b) 修复是否引入了新问题？

**预期效果**: 减少假阳性 Critic 通过（Critic 可能说"OK"但代码实际跑不通）

---

### 🟡 P1 — MCGS 搜索增强（3-5 天）

#### P1-1: 渐进式探索衰减

**设计文档**: MCGS 带分段衰减探索常数 `C(t)`，从 1.414 线性衰减到 0.5

**实现**:
1. `engine/mcts.py` `uct_value()`: 接收 `progress_ratio`（当前 gen / max_gens）
2. `C(t) = C_max - (C_max - C_min) * min(progress_ratio / decay_point, 1.0)`
3. 配置参数: `uct_C_max`, `uct_C_min`, `uct_decay_progress` (默认 0.5)

**预期效果**: 前期探索、后期收敛，避免早期陷入局部最优

#### P1-2: 探索-利用软切换

**设计文档 / MLEvolve**: `P(UCT) = w(t)`, `P(Top-K exploitation) = 1-w(t)`

**实现**:
1. `engine/selection.py`: 新增 `select_with_soft_switch()` 方法
2. `w(t)` 从 1.0（全探索）线性衰减到 0.2（偏利用）
3. 切换点: `progress_ratio` ∈ [0.5, 0.7] 区间内衰减
4. Top-K 利用: 全局最高分 top-5，按 1/rank 加权随机选择

**预期效果**: 搜索效率提升，减少后期无意义探索

#### P1-3: 强制反向传播（Forced Backpropagation）

**MLEvolve**: 后期阶段 50% 概率直接反向传播（不继续 improve 链），中期每 3 个节点触发一次

**实现**:
1. `engine/mcts.py`: `should_force_backprop(current_gen, max_gens)` 判定
2. 后期（>80% progress）50% 概率直接反向传播
3. 中期（>40% progress）每 3 个节点反向传播一次
4. 反向传播时写入 `candidate_search_state.visit_count += 1`

**预期效果**: 加速收敛 + 保持分支多样性

---

### 🟢 P2 — Prompt 工程增强（3-5 天）

#### P2-1: Director 分层改进策略

**设计文档 / MLEvolve**: 分级改进策略：L1 微调 → L2 架构变更 → L3 范式转变

**改动**:
1. `director.py` System Prompt: 注入 3 层改进策略
2. 停滞检测后自动升级层级（`max_stagnation_gens` 触发）
3. `AgentContext` 新增 `stagnation_level: int` 字段
4. Prompt 附带反例集合（从 `_failed_directions` 取）

**预期效果**: Director 思想质量提升，减少无效思想生成

#### P2-2: Coder 丰富上下文

**设计文档**: Coder 获得"父代、兄弟、引用分支摘要、eval 历史"

**改动**:
1. `fast_loop.py`: 加载兄弟节点（同一 island，最近 2 代）
2. `coder.py` `_build_user_message()`: 新增 `## Sibling Approaches` 区块
3. 扩展 `AgentContext`: `sibling_summaries: list[str]`
4. inspiration programs 截断从 800 字提升到 1500 字（token budget 充足时）

**预期效果**: Coder 生成代码更精准，少走重复弯路

#### P2-3: Memory 检索质量提升

**现状**: `memory_summaries` 只取 `outcome_summary[:200]`，缺少代码片段和完整上下文

**改动**:
1. `fast_loop.py`: memory 检索时加载 `code_diff_hash` 内容（前 500 字）
2. 记忆格式化: `[L1/SUCCESS]  score=X → 改动: {diff 前 200 字} → 效果: {outcome 前 150 字}`

**预期效果**: 记忆检索信息量提升 5-10 倍

---

## 三、时间线估计

| 阶段 | 内容 | 天 |
|------|------|-----|
| P0-1 | 评估失败反馈闭环 | 0.5 |
| P0-2 | Critic 沙箱反馈增强 | 0.5 |
| **P0 小计** | **阻塞主线** | **1** |
| P1-1 | 渐进式探索衰减 | 1 |
| P1-2 | 探索-利用软切换 | 1 |
| P1-3 | 强制反向传播 | 1 |
| **P1 小计** | **MCGS 搜索增强** | **3** |
| P2-1 | Director 分层改进策略 | 1.5 |
| P2-2 | Coder 丰富上下文 | 1 |
| P2-3 | Memory 检索质量提升 | 0.5 |
| **P2 小计** | **Prompt 工程增强** | **3** |
| **总计** | | **7 天** |

---

## 四、验证方案

每阶段完成后运行:

```bash
# 1. 单元测试
make test

# 2. 分层 LLM 测试
.venv/bin/python -m pytest tests/llm/test_llm_smoke.py -v

# 3. 全流程 E2E（sort + heilbronn，各 5 代）
PYTHONPATH="examples/python_optimization:$PYTHONPATH" \
  .venv/bin/python -m omnievolve.cli run \
  examples/python_optimization/initial_code.py \
  -e evaluator:SortEvaluator \
  -c configs/sort_optimization.toml --trusted --gens 5

# 4. 验收标准:
# - P0 完成后: sort 通过率 > 40%（当前 19%）
# - P1 完成后: best 分数方差降低 > 50%（多次运行稳定）
# - P2 完成后: heilbronn 平均 best 分数 > 0.3（当前 ~0.02）
```

---

## 五、不在本次计划内（v0.4+）

- Docker 沙箱默认启用（当前 `--trusted` 足够验证）
- HardenedBackend 生产化（gVisor/nsjail）
- 多模式代码生成（MLEvolve 的三步 Coder）
- PromptEvolver 自动进化（已有框架，缺数据驱动）
- Token/cost 追踪修复（当前 total_tokens=0）
- AsyncEngine 生产化
