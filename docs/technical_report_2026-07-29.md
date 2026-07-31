# OmniEvolve 运行时闭环、功能验证与研究校准报告

初始日期：2026-07-29

最后同步：2026-07-31

## 执行结论

OmniEvolve 已具备“单机、可恢复、可审计、可消融的代码进化研究框架”的工程形态。
本轮没有继续堆叠复杂 MCTS 或全面 MAP-Elites，而是优先保证已启用机制真实影响搜索：

- CAS 继续作为默认代码后端，Git 仅保留为可选 provenance 后端；
- `lineage_ucb` 是诚实的 canonical selector，旧
  `progressive_mcgs` 仅作为一个 schema 周期的兼容别名；
- novelty、岛屿 locality、stagnation、角色路由、policy genome liveness、
  progressive evaluation、Slow Loop canary 和 resume 均已有运行时闭环及测试；
- 最小 behavior-cell QD archive 与 operator UCB/Thompson portfolio 已实现为默认关闭、
  可独立消融的实验模块，没有重写主搜索状态；
- 研究 runner 已有幂等队列、租约、并发上限、错误分类、重试、原始尝试 provenance、
  配对统计和 strict replay。

当前不能宣称“正式基准已经证明 OmniEvolve 优于全部基线”。冻结 evaluator 校准已完成，
三任务、五变体、三种子的 v10 45-run pilot 也已执行完毕，但它以 32 completed、13 failed
结束，非算法性失败率 28.9%，没有通过不高于 5% 的升级门。因此 operator/QD 正式消融
清单只生成、不执行。这个 fail-closed 结果比在 provider 波动下产生一批不可解释数字更可信。

## 对改进报告的落实

### P0：结论可信度

1. 所有 Fast Loop 评估经统一 EvaluationService 进入静态校验、反作弊、
   progressive stages、hidden tests、重复 benchmark、聚合和 commit。
2. `compute_budget_sec = 0` 统一表示不限时；checkpoint 只推进到完整 commit
   的下一代。
3. checkpoint 覆盖 RNG、island、LineageUCB、router、budget、policy、
   QD archive、operator portfolio 和任务状态。
4. 未知模型价格贯穿为 `cost_usd = null, cost_known = false`。已知 subtotal
   仍可审计，但不会冒充完整总成本，也不会作为零成本进入比较。
5. strict replay 不再只检查进程退出码：
   - FakeLLM + fake evaluator 的 engine invariant 比较 lineage、artifact hash、
     score、路由、预算和 checkpoint；
   - 有运行时 benchmark 的 research replay 分开报告 artifact/lineage 严格等价
     和 noisy metric 非 bit-exact，避免虚假确定性。

### P1：用实验选择机制

1. 新增最小 `BehaviorArchive`：
   - AST 结构、代码规模、运行时区间组成 behavior descriptor；
   - 每岛、每 cell 一个 elite；
   - 父代采样严格 island-local；
   - checkpoint 可恢复，配置不兼容时 fail closed。
2. 新增 `OperatorPortfolio`：
   - `point`、`diff`、`rewrite`、`crossover`、`repair`；
   - task/stagnation stage 条件化；
   - UCB 或 Thompson 调度；
   - 以相对父代增益回传，只在串行 commit 区更新。
3. 新增独立研究协议：
   - operator：`operator_fixed`、`operator_ucb`、`operator_thompson`；
   - QD：`qd_off`、`qd_on`；
   - 分 protocol 配对，不让不同实验同名 variant 相互污染；
   - 精确 paired randomization、Holm correction、Cliff's delta、
     standardized effect 和功效分析。

### 暂不引入

- 真 DAG MCGS、rollout 和 PUCT；
- continuous steady-state async；
- 全面 MAP-Elites 状态重写；
- 把 Git 文本 merge 当作语义 crossover。

这些机制只有在当前 pilot 通过、且独立消融显示稳定收益后才值得增加复杂度。

## 功能与质量验证

### 自动化测试

- 针对成本、provider fallback 和 E2E 的回归：52 passed；
- research runner/replay 定向测试：10 passed；
- 完整非 slow suite：992 passed、7 skipped、2 deselected；
- 全仓 Ruff：通过；
- deterministic resume invariant：包含 QD/operator adaptive state，已通过；
- CAS `sort` CLI：1 代、1 个 evolved candidate、3 次 evaluator repetition，
  experiment completed，checkpoint generation 1。

普通 CI 明确排除真实 provider smoke。真实 smoke 使用 `llm_smoke`/`slow` marker
手动执行，避免凭据或网络状态污染常规测试。

### 三 provider 功能测试

凭据仅存放在 gitignored `.local.env`，未写入日志、测试产物、报告或 Git。

| 路径 | 模型 | 观测 |
|---|---|---|
| BigModel primary | `glm-5.2` | 多次成功；被选为当前工程校准的 primary |
| Beijing Aliyun fallback | `qwen3.8-max-preview` | 探针成功，但 Coder 尾延迟和超时高于 primary |

网关修复了自定义 OpenAI-compatible base 缺少 provider prefix 的问题；永久鉴权/
模型错误会禁用对应 credential 或 endpoint，后续角色调用不重复无效重试。旧
`qwen3.7-flash` 已退出测试配置，不再作为可用路径描述。

一次 bounded Heilbronn 完整 smoke 正确失败：primary 无权限、GLM 返回空 final、
Beijing Qwen 超时，最终没有伪造 evolved candidate。此前 CAS `sort` 完整 E2E
以及后续 research `sort` cells 均成功，说明框架路径可工作，但这组三方服务当前
没有稳定到足以支撑完整正式矩阵的共同 SLA。

## Evaluator 噪声校准

冻结候选、最少 3 次、最多 10 次重复，目标为 95% CI 半宽低于 5% minimum effect：

| 任务 | 重复数 | 均值 | 95% CI 半宽 | 收敛 |
|---|---:|---:|---:|---|
| sort | 3 | 0.5000592 | 0.0000154 | 是 |
| nqueens | 3 | 1.0 | 0 | 是 |
| circle_packing | 3 | -0.15 | 0 | 是 |

v10 校准产物位于 `.omnievolve/research/calibration-v10-20260730.json`。45-run pilot manifest 已生成，
包含校准文件绝对路径和 SHA-256，缺失或变更时 `plan-pilot` fail closed。

## 工程 pilot 结果

### 可恢复 random-search baseline

`sort`、`nqueens`、`circle_packing` × seeds 11/22/33 共 9 runs：

- completed 9/9；
- failed 0；
- retried 0；
- provenance valid 9/9；
- 无 LLM 调用，已知成本为 0；
- strict replay：artifact、lineage、RNG 与核心配置指纹完全一致；
- runtime benchmark 分数非 bit-exact，按设计单独标记为 noisy metric。

### sort 单代、三种子工程消融

以下都是 1 generation、population 1、3 次 evaluator repetition；样本量仅用于
工程校准，不能外推为正式算法结论。

| variant | n | AUC mean | AUC 95% CI | best mean | tokens mean | wall mean (s) |
|---|---:|---:|---:|---:|---:|---:|
| random_search | 3 | 0.500065 | [0.500065, 0.500066] | 0.500066 | 0 | 25.3 |
| single_agent | 3 | 0.517975 | [0.516246, 0.519704] | 0.535885 | 1481.7 | 47.7 |
| no_novelty | 3 | 0.508803 | [0.485431, 0.532175] | 0.517542 | 3009.7 | 90.0 |
| no_slow_loop | 3 | 0.518220 | [0.514798, 0.521642] | 0.536375 | 3036.3 | 52.2 |

相对 random search 的 paired AUC 差异：

- `single_agent`: +0.017910，95% CI [0.016180, 0.019639]；
- `no_novelty`: +0.008738，95% CI [-0.014634, 0.032110]；
- `no_slow_loop`: +0.018155，95% CI [0.014732, 0.021577]。

解释边界：

- `single_agent` 在这个极小预算下以约一半 token 达到接近多角色版本的 AUC，
  值得在正式矩阵继续检验；
- `no_novelty` 方差显著更大且一个 seed 未超过 baseline，方向不确定；
- `no_slow_loop` 只有 1 代，本来就不能测量 Slow Loop 的价值；
- provider 输出随机且价格未知，因此不能做 cost-improvement 结论。

### v10 45-run pilot 最终状态（2026-07-31）

| 状态 | runs |
|---|---:|
| completed | 32 |
| failed | 13 |

- `random_search`、`single_agent`、`no_slow_loop` 各完成 9/9；
- `full` 完成 2/9，7 次因没有完成独立 policy canary 而 fail closed；
- `no_novelty` 完成 3/9，5 次因没有完成独立 policy canary 而 fail closed，1 次因没有 evolved candidate 记为 infrastructure failure；
- 12 次失败归类为永久配置/鉴权/完整性，1 次归类为 infrastructure；
- 32 个完成结果的 provenance 污染为零。

pilot gate 仍为失败：13/45 的失败率为 28.9%，显著高于协议允许的 5%，并且多个
`full`/`no_novelty` cell 没有至少两个有效配对 seeds。正式 operator 135-run 与 QD
90-run manifest 已生成，但按照协议没有越过门禁执行。v10 数据只用于工程诊断，
不得进入正式算法结论。

## 当前差距与下一步门槛

1. 稳定 `full` 与 `no_novelty` 的 canary 触发/完成率，避免运行结束时两者退化为 `no_slow_loop`；
2. 对 Coder 尾延迟设置可执行的 arm wall/token 预算，并保持 provider fallback 可审计；
3. 重跑三任务 × 五变体 × 三 seeds pilot，并满足：
   provenance 污染为零、非算法失败率不高于 5%、每 cell 至少两个有效配对 seeds；
4. 用 paired variance 做功效分析，正式 seeds 限制为 5–10；
5. pilot 通过后，先独立跑 operator，再独立跑 QD；不同时打开；
6. 若 10 seeds 仍 underpowered，报告 underpowered，不扩大结论。

## 最终工程判断

设计整体是恰当的，不是过度设计，前提是坚持“默认主干简单、实验机制可关闭、
门禁失败不硬跑”的原则。CAS、islands、LineageUCB、统一评估、checkpoint 和
本地任务队列构成稳定主干；QD 与 operator portfolio 目前只是有明确 runtime
effect 的可消融扩展。真正仍欠缺的不是更多搜索名词，而是稳定 provider、完整
paired evidence，以及多文件语义 crossover/LLM fallback 的进一步验证。
