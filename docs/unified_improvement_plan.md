# OmniEvolve 统一改进计划（合并版 · 本地化）

- 状态：**计划（未实施）**，待确认后按阶段推进
- 日期：2026-08-03
- 合并来源：
  1. **论文 verifier 线**：LLM-as-a-Verifier 集成（详见 `docs/llm_as_verifier_integration_plan.md`，PR1-3 已完成、PR4-6 未开始）
  2. **实测降本线**：基于 SSWevolve 单数据进化实验的实测瓶颈分析
- 硬约束：**不依赖 logprobs**（GLM-5.2 coding 端点实测不返回 token logprobs）

---

## 1. 本地环境与基线（定位依据）

| 维度 | 本地事实 |
|---|---|
| 硬件 | 10× NVIDIA A40（驱动 570.211.01 / 最高 CUDA 12.8） |
| 生成模型 | GLM-5.2（bigmodel coding 端点），推理模型，**不返回 logprobs**（实测） |
| 嵌入模型 | Qwen3-Embedding-0.6B（本地 cuda，dim=1024，HF 离线） |
| 任务 | SSWevolve 单数据（指数序列）评估器 `examples/sswevolve/evaluator.py` |
| 实验 | experiment `47927aada921`，已优雅停止于 gen 15/20 |
| 最优结果 | **F=+0.0557**（候选 `b05b30eb3f05`，gen 4）；v3 基线 F=-0.0357 |
| 最优候选指标 | s_ssw=0.0496，s_um=0.0167，s_sec=0.0133，**cov80=0.736（<0.80）**，n_params=14 |
| Token 开销 | 89 次调用、634,880 tokens（coder 452k / director 183k）；**输出/推理 token 占 ~63%** |
| 质量瓶颈 | 43 次评估、通过率 **55.8%**（~44% L1 失败）；失败候选快（0.4s），通过候选贵（均 16.4s mini-CV） |

**两大实测瓶颈** → 改进重心：
1. 开销大头 = **GLM 推理/输出 token**（占 63%）。
2. 质量损耗大头 = **生成了最终 L1 无效的 CLOSURE**（浪费生成 token）。

---

## 2. 优先级总览（按本地 ROI 排序）

| # | 项 | 来源 | logprobs? | 本地依据 | 优先级 |
|---|---|---|---|---|---|
| P0 | 固化最优成果 + 冻结基线 | — | 无需 | F=+0.056 已达成 | ★★★ 立即 |
| 1.1 | 推理/输出 token 预算化 | 实测 | 无需 | 输出 token 占 63% | ★★★ |
| 1.3 | 静态 schema 预检 | 实测 + 论文准则分解 | 无需 | 44% L1 失败 | ★★★ |
| 2.1 | 结构化失败反馈 + schema 预置 | 实测 | 无需 | 44% L1 失败 | ★★★ |
| 2.3 | cov80 定向改进 | 实测 | 无需 | cov80=0.736<0.80 | ★★ |
| 1.2 | 上下文相关性裁剪 | 实测 | 无需 | 输入 token 冗余 | ★★ |
| 2.2 | 记忆引导反重复 | 实测 | 无需 | 已有 L0-L4 记忆 | ★★ |
| 2.4 | 离散集成 tie-breaker（PR4 的 logprobs-free 版） | **论文** | **无需** | 打平候选多 | ★★ |
| 3.1 | 确定性去重 + 渐进评估 | 实测 | 无需 | mini-CV 昂贵 | ★ |
| 3.2 | 算子组合 / 父代选择调优 | 实测 | 无需 | 种群小 | ★ |
| 4.x | 概率 verifier 满血版（PR4/5/6）、VOC | **论文** | **需要** | GLM 无 logprobs | ⏸ 暂缓 |

---

## 3. 分阶段计划

### Phase 0 — 固化成果 + 基线（无代码，立即）
- 导出最优候选 `b05b30eb3f05` 的 CLOSURE（F=+0.0557），存档到 `references/SSWevolve` 之外的独立位置。
- 冻结当前 config / seed / 评估器版本，作为后续所有改进的**对照基线**。
- 本地意义：SSWevolve 单数据实验已显著超越 v3 锚点（F -0.036 → +0.056）。

### Phase 1 — 立即降本（logprobs-free，低风险，先做）
- **1.1 推理/输出 token 预算化**：按角色差异化 `max_tokens` + 简洁 SEARCH/REPLACE 提示 + **输出完整性守卫**（检测到截断则加大预算重试）。
  - 模块：`config.py` `ModelsSettings.max_tokens`、`agents/coder.py`、`agents/director.py`。
  - 依据：GLM 推理受 `max_tokens` 约束；输出 token 占 63%。
  - 风险：上限过低导致截断 → 用守卫重试 + 安全下限缓解。回滚：config 还原。
  - **✅ 已实施（2026-08-06，`feature/arch-improvement`）**：`role_max_tokens` 角色级预算 + `LLMGateway` 截断守卫（自动扩容重试）。详见 `docs/arch_improvement_log.md`。
- **1.2 上下文相关性裁剪**：只注入 top-k 相关记忆（复用 embedding 相似度）；压缩 SSWevolve 冻结骨架（EVOLVE-BLOCK 外恒定，可摘要）。
  - 模块：`agents/context_builder.py`、`retrieval_budget`。
  - 回滚：阈值还原。
  - **✅ 已实施（2026-08-06，`feature/arch-improvement`）**：ContextBuilder 死代码接线为单一入口（Director/Coder 提示保真迁移 + 角色预算裁剪）。详见 `docs/arch_improvement_log.md`。
- **1.3 静态 schema 预检（pre-sandbox）**：沙箱前确定性校验 CLOSURE（eq_name 白名单 `U_L/U_M/U_U/W1r/W1i/W2r/W2i/H1/H2`、states≤3、仅 numpy/math import），无效直接短路返回 `fail_reason`。
  - 模块：`examples/sswevolve/evaluator.py`、`runner.py`。
  - 论文关联：这是"准则分解"的本地化落地，但用确定性检查替代 LLM/logprobs。
  - 风险：与真实 L1 不一致 → 以真实 L1 为准，预检只做高置信快速短路。回滚：开关关闭。

### Phase 2 — 提升通过率与质量（logprobs-free，代码级）
- **2.1 结构化失败反馈 + schema 预置**：把精确 L1/L2 失败原因 + 合法 schema 注入下一次 coder 提示。
  - 目标：直接压低 44% 的 L1 失败率。模块：fast_loop 反馈路径、`coder.py`。
- **2.2 记忆引导反重复**：强化把 failed-directions（L0-L4 记忆 + meta_scratchpad）注入 Coder"避免清单"。
  - 模块：`engine/fast_loop.py`、`engine/memory.py`、`director.py`/`coder.py`。
- **2.3 cov80 定向改进**：cov80=0.736 低于 0.80 目标（罚项 ~0.064），在提示中显式引导校准覆盖趋近 0.80。
  - 本地意义：当前最优解仅剩的明显短板，针对性再进化。
- **2.4 离散集成 tie-breaker**（论文 PR4 的 logprobs-free 版）：任务分数打平（差异 < tolerance 或 CI 重叠）时，用 K 次 A/B 成对比较（奇偶交换位置）聚合，给 `search_score` 加**有界** bonus，影响 LineageUCB。
  - 约束：作为独立诚实模式（不伪装成 logprob 概率）；不触碰 `passed`/`primary_score`。
  - 本地意义：SSWevolve 分数噪声大、打平多；这是**不依赖 logprobs 就能承接论文价值**的关键点。

### Phase 3 — 搜索效率增益
- **3.1 确定性去重 + 渐进评估**：CAS artifact hash 去重，避免重复评估相同代码；`progressive_eval_enabled` 让候选先过廉价阶段。
  - 模块：`evolution_engine`、`evaluation_service`、config。
- **3.2 算子组合 / LineageUCB 调优**：`operator_portfolio_enabled`（UCB 学习有效变异算子）。
  - 模块：`engine/operator_portfolio.py`、`engine/selection.py`。成本中性、增益型。

### Phase 4 — 论文概率 verifier 满血版（⏸ 暂缓，logprobs 依赖）
- **前置门禁**：要用 PR4/5/6 概率版，必须先在 A40 上本地起一个 **logprobs 能力的开源 verifier**（或 two-stage：GLM 推理 + 开源模型打 logprob）；否则整条线无法激活。
- **本地决策**：因"不依赖 logprobs"，Phase 4 整体**暂缓**；其价值由 **1.3（准则分解预检）** 与 **2.4（离散 tie-breaker）** 提前承接。
- 子项（将来启用）：PR4 概率 search credit / PR5 自适应 benchmark 分配 / PR6 island-local PPT（种群大时）/ VOC 任务进度代理。

---

## 4. 隔离与验证纪律（本地化）
- 原实验 `examples/sswevolve/.omnievolve/` 结果 DB **保持原样不动**（含 F=+0.056 最优候选与记忆）。
- 所有开发在**独立 git 分支**；新验证运行用**独立目录 + 独立 db_path**，不复用原实验。
- 每项先 **FakeLLM / 离线回放 → 独立目录小规模 A/B → 对照 P0 基线**，通过再谈合入。
- GLM 配额：离线验证不耗 token；live 验证用独立小预算（必要时独立 key）。

---

## 5. 建议的执行顺序
1. **Phase 0**（导出最优 CLOSURE + 冻结基线）。
2. **Phase 1.1 + 1.3**（最省钱、最低风险）。
3. **Phase 2.1 + 2.3**（直接提通过率与补 cov80 短板）。
4. 其余按优先级推进；**Phase 4 暂缓**，待将来决定部署本地 logprobs verifier。
