# OmniEvolve 架构改进实施日志

> 分支：`feature/arch-improvement`（与 `main` 研究线隔离，仅框架本体 `src/omnievolve/`）
> 计划来源：`docs/unified_improvement_plan.md`（SSWevolve 比赛侧改动不进入本分支）

每完成一个改进项追加一节，记录：改动、设计决策、验证、回滚方式。

---

## 1.1 推理/输出 token 预算化 — 已实施（2026-08-06）

### 目标
GLM 推理/输出 token 占实测开销 63%。按角色差异化 `max_tokens` 上限直接约束推理 token，
截断时由输出完整性守卫兜底，避免"上限过低 → 内容截断"的质量损失。

### 改动
| 文件 | 内容 |
|---|---|
| `src/omnievolve/config.py` | 新增 `DEFAULT_ROLE_MAX_TOKENS`（director=2048 / coder=4096 / critic=1024 / meta=2048）；`ModelsSettings.role_max_tokens`；`_build_settings` 支持 TOML 部分覆盖（与默认合并） |
| `src/omnievolve/agents/llm_gateway.py` | `LLMResponse.truncated` 字段；`LLMGateway(role_max_tokens=...)` 构造参数（越界钳制到全局上限）；`chat()` 未显式 `max_tokens` 时按 `agent_role` 应用角色预算；截断守卫（`finish_reason=="length"` 且预算 < 全局上限时复用 attempt 循环扩容重试一次）；`fork()` 继承角色预算 |
| `src/omnievolve/cli.py` | `_apply_llm_env_overrides` 返回 `role_max_tokens`，随 `**llm_kwargs` 注入网关 |

### 设计决策
- **网关层自动应用角色预算**：coder/director/critic 等 agent 零改动，仅按既有 `agent_role` 参数路由。
- **截断守卫复用 attempt 循环**：不算失败、不 sleep、不重复记账；默认 `max_retries=3` 足够覆盖"一次截断扩容 + 一次成功"。
- **钳制语义**：角色预算永远 ≤ 全局 `max_tokens`；已到全局上限仍截断时不再扩容，`truncated=True` 留给调用方。
- `score_tokens()`（verifier 通道）不受影响——granularity 固定，不适用角色预算。

### 验证
- 新增 `tests/agents/test_token_budget.py`（13 例）：角色预算生效 / 未知角色回退全局 / 显式参数优先 /
  越界钳制 / 截断扩容重试（2048→8192）/ 全局上限标记 truncated / config 默认与 TOML 部分覆盖。
- `tests/test_config.py`、`tests/test_cli.py` 回归通过（`test_cli.py` 断言 `kwargs["default_max_tokens"]` 不变）。

### 回滚
- config 还原 `role_max_tokens` 默认空（网关回退全局上限）；或仅还原 `config.py`/`cli.py` 的传递链。
- `LLMResponse.truncated` 为带默认值新字段，无破坏性。

---

## 1.2 上下文相关性裁剪（ContextBuilder 接线）— 已实施（2026-08-06）

### 目标
`ContextBuilder` 自 S5-05 起被实例化却从未接线（死代码），Director/Coder 各自手写
拼接提示，输入 token 无统一预算控制。本项将其接为上下文构建的**单一入口**。

### 改动
| 文件 | 内容 |
|---|---|
| `src/omnievolve/agents/context_builder.py` | 新增 `build_director_user_message(ctx)` / `build_coder_user_message(ctx, thought)`（AgentContext 完整版）；从 Director/Coder 的 `_build_user_message` **保真迁移**（标题、顺序、截断阈值不变）；末尾统一按角色预算截断 |
| `src/omnievolve/agents/director.py` | 构造注入 `context_builder`；`_build_user_message` 委托 builder |
| `src/omnievolve/agents/coder.py` | 同上（`_get_parent_code` 保留给 diff 解析） |
| `src/omnievolve/engine/evolution_engine.py` | 共享 `ContextBuilder(total_token_budget=min(token_budget, 100_000))` 注入 Director/Coder |

### 设计决策
- **保真迁移**：`tests/agents/test_eval_feedback.py` 断言 prompt 标题顺序
  （父代码 → 失败反馈 → inspiration），迁移后顺序一致，测试零改动通过。
- **单一逻辑源**：agents 默认构造也建 builder（无引擎注入时行为一致），
  消除双份提示逻辑漂移风险。
- 保留旧 `build_director_context`/`build_coder_context`（简单参数版）为兼容 API。

### 验证
- 新增 `TestFullContextBuilders`（7 例）：已知区块齐全 / 无停滞省略 Tier /
  顺序保真 + root cause / 预算裁剪生效 / 父代码提取。
- 回归：agents 70 例 + e2e 14 例全部通过。

### 回滚
- agents 构造不传 `context_builder` 即回退默认实例；行为与迁移前一致。

---

## 3.1 确定性去重（渐进评估已存在，补去重）— 已实施（2026-08-06）

### 目标
计划 §3.1 含"确定性去重 + 渐进评估"两块。核查发现**渐进评估已由
`EvaluationService` 完整实现**（progressive stages + early stop + repetitions），
本项补齐缺失的**确定性去重**：相同 `artifact_hash`（CAS 内容 hash）的代码
已有完成评估时直接复用结果，跳过昂贵 sandbox（通过候选 mini-CV 均 16.4s）。

### 改动
| 文件 | 内容 |
|---|---|
| `src/omnievolve/config.py` | `EvolutionSettings.dedup_reuse_enabled`（默认 True）+ `build_evolution_config` 传递 |
| `src/omnievolve/engine/evolution_engine.py` | `EvolutionConfig.dedup_reuse_enabled` |
| `src/omnievolve/engine/fast_loop.py` | `_execute_sandbox` 开头查重；新增 `_reuse_duplicate_eval`：命中时返回复用 `EvalOutput`，跳过 sandbox/job/eval_run |

### 设计决策
- **复用语义**：CAS 下 `artifact_hash` 即代码内容 hash，相同代码在相同
  evaluator/environment/seed 下结果确定；复用结果在 metrics 中标记
  `dedup_reused` + `dedup_source_candidate` 保证可审计。
- **不重复计 sandbox 预算**：`_apply_eval_result` 中 `result=None` 时
  BudgetGuard 跳过（既有 None 保护），未执行 sandbox 不消耗预算。
- **不建新 eval_run**：旧 run 已完整记录该 (hash, evaluator, environment, seed)
  的评估；新 candidate 复用不违反 EvaluationRun 幂等红线（键含 candidate_id）。
- 谱系/搜索状态完整：candidate 记录仍创建，仅评估结果复用。
- 开关默认 True；可回滚（关闭即恢复重复评估）。

### 验证
- 新增 `tests/engine/test_dedup_reuse.py`（4 例）：命中复用（score/passed/
  metrics/审计标记/跳过 sandbox）/ 未命中 / 开关关闭不查库 / 失败候选复用。
- 回归：config 8 例 + e2e 14 例通过。

### 回滚
- `evolution.dedup_reuse_enabled = false` 即关闭；或还原 fast_loop 查重调用。

---

## 待办

- [ ] 2.1 结构化失败反馈（框架侧增强）
- [ ] 2.2 记忆引导反重复（框架侧增强）
- [ ] 2.4 离散集成 tie-breaker（logprobs-free）
- [ ] 3.2 算子组合 / LineageUCB 调优
