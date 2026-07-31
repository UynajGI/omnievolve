# Evolve 文献与开源工程对标

> 本文的“当前差距”是 2026-07-29 的代码快照。运行时闭环、真实 canary、
> deterministic resume 和研究 runner 的后续落地状态，以
> [运行时闭环与研究校准报告](technical_report_2026-07-29.md) 为准；文献判断保留为历史研究依据。

> 调研日期：2026-07-29  
> OmniEvolve 基线：`7cf4dded6bed5b109e55032d7611cd0a0454b7a7`  
> 定位约束：单机研究框架；CAS 为默认代码后端；Git 仅作为可选谱系后端
>
> 实施更新：本文的缺口描述针对上述基线。其后已完成 novelty 两级语义、
> 岛内选择、generation-best stagnation、角色路由归因、统一评估、
> deterministic resume、真实等预算 canary 和研究统计协议闭环。尚未获得的
> 是正式 pilot 证据，以及 operator bandit / 最小 QD archive 的独立消融结果。

## 结论

OmniEvolve 已经是一个功能完整度较高的“程序进化研究工作台”，但还不能称为
一个被实验证明有效的 evolve 框架。它当前最强的部分不是搜索算法本身，而是：

- CAS、多文件快照、图谱、checkpoint、租约恢复和失败重试；
- 分阶段评估、隐藏挂载完整性检查、静态反作弊；
- 九任务、五种变体、多种子、重复测量、bootstrap 置信区间和回归检测协议；
- 同步与异步 prepare/commit 分离，以及可审计的研究队列。

主要问题是“机制增长快于证据增长”。代码已经同时拥有 MCGS、Top-K
软切换、tournament fallback、island、novelty、reference credit、Slow Loop、
模型路由和多种 mutation，但本地只有 smoke/fail-closed 结果，没有完成的
多任务消融矩阵。因此下一阶段不应继续横向增加搜索组件，而应先修正两个
研究结论会被直接污染的问题，然后用实验决定删留。

最重要的两个问题是：

1. **Slow Loop 目前不是真正的 challenger replay。**  
   `src/omnievolve/engine/slow_loop.py:189-203` 创建新策略后，没有用新策略
   重新执行候选；它把 `recent_scores[-health_window_gens:]` 当 champion，
   把同一历史中的 `recent_scores[-1:]` 当 challenger。这个比较不能归因于
   策略变化。`self_evolve_enabled` 当前却默认开启。修复前应默认关闭 Slow
   Loop，也不应宣称已实现有效的自进化。

2. **基线中的选择配置与实际执行不一致。**  
   当时 `SelectionSettings.parent_selector` 默认写着 `progressive_mcgs`，但
   `EvolutionEngine` 另建 `ProgressiveMCGS`，同时把 fallback
   `ParentSelector` 硬编码为 `tournament`。实际父代选择又叠加 MCTS、
   Top-K 软切换和 island elite。配置项没有完整控制运行时策略，也没有
   单一、可审计的选择决策入口。

一句话判断：**框架不是整体过度设计，而是搜索控制面和 Slow Loop 出现了
局部过度设计；评估、存储和恢复能力则是恰当且有价值的设计。**

## 文献与开源库地图

| 系统 | 主要进化对象与机制 | 对 OmniEvolve 的启示 |
|---|---|---|
| [FunSearch](https://www.nature.com/articles/s41586-023-06924-6) | 在固定 skeleton 中进化关键函数；高分程序数据库、island 和自动 evaluator | 不要默认重写整个项目。显式定义 evolve zone，往往比扩大代码搜索空间更可靠、更省 token |
| [AlphaEvolve](https://arxiv.org/abs/2506.13131) | LLM ensemble 直接改代码，以一个或多个自动 evaluator 持续反馈 | OmniEvolve 的主循环方向正确；真正壁垒仍是 evaluator 质量、计算预算分配和实验结果，而不是组件数量 |
| [OpenEvolve](https://github.com/algorithmicsuperintelligence/openevolve) | MAP-Elites、island、LLM ensemble、错误 artifact side-channel 和可视化 | OmniEvolve 有 island 和多维指标，但没有真正以行为描述符分箱的 QD archive；当前 novelty gate 不能替代 MAP-Elites |
| [ShinkaEvolve](https://github.com/SakanaAI/ShinkaEvolve) | weighted/power-law/beam 父代选择、动态 island、异步执行、重复评估、public/private 指标、Local/Slurm runtime | 单机定位无需复制 Slurm，但应借鉴独立采样/评估/提交限流，以及 evaluator 的 private 指标边界 |
| [CodeEvolve](https://arxiv.org/abs/2510.14150) | island GA、inspiration crossover、祖先上下文、CVT-MAP-Elites；公开消融和预算参数指南 | 与 OmniEvolve 最直接的对照。其结果提示 ancestor、inspiration、MAP-Elites 和迁移拓扑必须分别消融，不能因为代码存在就视为有效 |
| [EoH](https://arxiv.org/abs/2401.02051) | 思想与代码共同进化；在组合优化上与 code-only 变体消融 | OmniEvolve 的 Director/Thought 设计有依据，但缺少 `thought+code` 对 `code-only` 的直接消融 |
| [LLaMEA](https://arxiv.org/abs/2405.20132) | 生成、执行、反馈、选择的精简元启发式进化循环 | 应加入“最小可用 evolve loop”基线，检验复杂控制面是否真的优于一个小而清楚的循环 |
| [MLEvolve](https://arxiv.org/abs/2606.06473) | Progressive MCGS、跨分支 reference edge、Retrospective Memory、分阶段 coding mode | OmniEvolve 已复现其结构思路，但 reference credit 仍是固定权重，memory/MCGS 也缺少 matched-budget 实证 |
| [Darwin Gödel Machine](https://arxiv.org/abs/2505.22954) | 进化 coding agent 自身代码，以 SWE-bench/Polyglot 经验验证，并保留开放式 archive | OmniEvolve Slow Loop 只修改策略字段和 prompt，不是 agent 源码自修改。当前单机研究阶段不必追 DGM 广度，但术语必须准确 |
| [A-Evolve](https://github.com/A-EVO-Lab/a-evolve) | 标准化 Agent、EvolutionEngine 和 BenchmarkAdapter，面向多域 agent evolution | 最值得借鉴的是接口边界和 benchmark adapter，而不是“零人工获得 SOTA”的产品叙事 |
| [Meta-Harness](https://arxiv.org/abs/2603.28052) | 外循环搜索 memory/retrieval/context 等 harness 代码，并让 proposer 读取全部代码、分数和执行 trace | 若未来扩展 Slow Loop，应把“可进化 harness”做成隔离、版本化的显式对象，而不是在主进程中散改参数 |
| [Vesper / Effective Harness Engineering](https://arxiv.org/abs/2605.15221) | coding agent 在隔离 worktree 中多步思考、调试；研究 evaluator hack、安全并行和 token 分配 | 对当前阶段最有价值：少而深的候选可能比多代浅采样更有效；更强模型反而更需要反作弊和 evaluator 隔离 |
| [DeepEvolve](https://arxiv.org/abs/2510.06056) | 把外部研究、跨文件编辑和系统调试接入进化循环 | 适合后续“research operator”，但必须把检索快照和引用固化进 run bundle，避免结果无法重放 |
| [ThetaEvolve](https://arxiv.org/abs/2511.23473) / [PACEvolve++](https://arxiv.org/abs/2605.07039) | test-time RL 或 trainable advisor，让搜索策略随任务反馈学习 | 是手写 Slow Loop 的长期替代方向；需要 GPU/训练稳定性，当前不应优先于可靠的 inference-only 基线 |
| [pyribs](https://docs.pyribs.org/en/latest/index.html) | 标准 QD archive、emitter、scheduler、MAP-Elites/CMA-ME/Novelty Search | 可借鉴接口和统计定义；不建议为了一个概念直接引入整套数值优化依赖 |

## 当前工程能力与真实差距

### 1. Search controller：能力强，但责任重叠

当前路径大致是：

```text
island elite
  -> MCGS 或全局 Top-K 软切换
  -> ParentSelector tournament fallback
  -> crossover / point / rewrite
  -> novelty gate
  -> staged evaluator
  -> MCGS backprop + island archive + router update
```

这条链不是错误，但存在三个问题：

- `selection.parent_selector` 没有成为真实运行时 contract；
- MCGS、Top-K、tournament、island elite 都在决定“从哪里继续”，很难从
  trace 中回答某次成功究竟来自哪一层；
- Slow Loop 又会改变 mutation mix、memory 权重和 prompt，进一步增加归因难度。

改进方式不是再加 selector，而是建立一个统一 `SelectionDecision`：

```text
candidate_id
policy_name
policy_version
island_id
explore_probability
candidate_set_digest
rank / UCT / posterior components
random_draw
reason
```

所有 MCGS、Top-K、fallback 和 island 决策必须通过这一接口并写入事件日志。
未知策略名应 fail closed，不能静默退化为 random 或另一个默认策略。

### 2. Slow Loop：当前是正确性问题，不只是研究不足

真正的 challenger 实验至少应满足：

- champion 与 challenger 从相同代码、数据库和 evaluator 快照开始；
- 使用配对种子、相同模型集合、token/时间/候选数预算；
- challenger 的结果必须由 challenger 策略独立执行得到；
- promotion 使用配对差值的 bootstrap CI、效应量和任务级退化门；
- 成本、失败率、有效候选率和前沿贡献同时纳入判定；
- 所有 challenger 失败也必须落盘，不能只保留成功者。

在这些条件完成前，建议：

```toml
[evolution]
self_evolve_enabled = false
```

保留 Slow Loop 代码用于研究，但不要默认参与普通 run。

### 3. Crossover：已经从文本拼接进步到 AST，但仍是单文件 Python 语义

`src/omnievolve/engine/crossover.py:129-147` 的 semantic crossover：

- 用 Python `ast.parse`；
- 以顶层 function/class 的类型和名称识别符号；
- 同名符号从父代中选一个完整 AST 节点；
- 新符号追加到主父代模块；
- 解析失败时回退到 feature merge。

它能显著减少纯文本冲突，但“CAS 支持多文件 manifest”不等于“搜索能做
repository-level semantic crossover”。仍缺少：

- 跨文件 symbol/reference graph；
- import、类型、调用约束和 build graph 的一致性；
- 同一功能跨多个符号协同变化；
- Python 之外语言的 parser；
- 语义冲突后的 LLM repair 及其独立计费、成功率统计。

建议下一步做 `ChangePlan -> per-file patch -> build/test -> repair`，以
tree-sitter/LSP 符号图或语言插件承载，不要尝试构造一个跨语言统一 AST。

### 4. Reference credit：实现谨慎，但不是因果归因

`ProgressiveMCGS.credit_references()` 的优点是：

- 默认权重 `0.25`；
- 只更新 reference 节点的 Beta 后验；
- 不伪造真实 visit；
- 不沿 reference 节点祖先继续传播，避免 DAG 多路径重复计权。

但当前仍把所有被检索/融合的 reference 等量记功，无法区分“被放入上下文”
与“真正被采用”。优先改为：

1. 记录生成器声明的 adopted references 和 symbol/diff 对应关系；
2. 奖励使用相对父代的增益，而不是绝对 child score；
3. 按采用比例归一化，保证一次 child 的 reference credit 总量有上限；
4. 对小比例样本做 leave-one-reference-out 复评，用于校准启发式权重；
5. 单独消融 fixed、adoption-weighted、credit-off。

不建议现在直接实现昂贵的 Shapley value。

### 5. Novelty/QD：有过滤器，没有可解释的质量-多样性 archive

当前 novelty 组合 embedding、AST signature、epiplexity 和可选 LLM judge。
它适合拒绝重复候选，却不能回答：

- 搜索覆盖了哪些行为区域；
- 每个区域的 elite 是谁；
- 新颖性是否换来了性能、鲁棒性或只是代码表面差异。

建议引入任务可提供的 `behavior_descriptor(candidate, eval_result)`，默认描述符可用：

- 任务行为：正确率分桶、不同输入规模上的性能斜率；
- 资源行为：执行时间、峰值内存、代码长度；
- 结构行为：循环/递归/向量化类别，而不是裸 AST 节点序列。

用小型 Grid/CVT archive 即可。先让 archive 成为可观测对照，不必立刻替换
现有 island。

### 6. Benchmark 与统计：协议已经不错，运行证据仍为空

当前默认矩阵是九任务：

`circle_packing`、`contract_cheaper`、`heilbronn`、`lennard_jones`、
`matmul`、`nqueens`、`occam_circuit`、`orbit_q`、`sort`。

默认五变体：

`full`、`random_search`、`single_agent`、`no_novelty`、`no_slow_loop`，
另有 reference-credit 配对矩阵。五种子时主矩阵为 225 个 job。runner
支持 repetition、租约、并发、重试和失败关闭，汇总器支持 bootstrap CI
与回归检测。

但是 `.omnievolve/research` 中目前只有 random smoke、provider
fail-closed 和 integrity probe；没有完成的主矩阵。因此当前能证明的是
“执行链和失败策略可工作”，不能证明“完整框架优于基线”。

推荐分两步执行：

1. **校准 pilot**：`sort + circle_packing + contract_cheaper`，五种子，
   每 job 两次重复，先测方差、失败率、墙钟和 API 成本。
2. **功效驱动的正式矩阵**：根据 pilot 方差确定每任务种子/重复数；高噪声
   benchmark 增加重复，低噪声任务不机械扩容。

报告应使用 task-level 配对差值、BCa 或 percentile bootstrap CI、
Cliff's delta/标准化效应量，并对多任务比较做 Holm 校正。总体平均分只作
摘要，不能掩盖任务级回归。

### 7. Replay 与反作弊：有基础，缺完整 provenance

当前 `replay.json` 记录 `argv`、`cwd`、`PYTHONHASHSEED` 和 git commit；
隐藏挂载检查 read-only 和 SHA-256，candidate scanner 会拦截显式窥探测试/
evaluator 的行为。这比许多开源 evolve clone 更严谨。

要达到 deterministic replay，还应把以下内容放入一个内容寻址的 run bundle：

- 完整解析后配置及 schema version；
- 初始代码、candidate manifest、task/evaluator/hidden dataset digest；
- Python/依赖 lock hash、OS、CPU/GPU、线程数和容器镜像 digest；
- provider、model canonical ID/revision、sampling 参数和响应 usage；
- prompt/template 版本、检索结果及顺序、原始 response artifact hash；
- 每阶段开始/结束事件、随机数流或可重放随机决策；
- evaluator stdout/stderr、失败类别和超时原因。

反作弊还应增加 evaluator mutation tests：故意构造读取 evaluator、根据
公开样例硬编码、跳过大输入和利用计时方式的候选，验证各任务是否 fail closed。

### 8. Runtime：单机方向正确，下一步是分阶段背压

当前异步引擎把 LLM+sandbox prepare 并行、共享状态 commit 串行；研究 runner
有本地 leased queue、并发限制和重试。这符合单机定位。

下一步只需增加三个独立 semaphore/queue：

- proposal：按 provider rate/token budget 限流；
- sandbox：按 CPU、内存和进程数限流；
- commit：单写者、幂等 event application。

避免一次 `gather` 等待整批最慢任务；使用完成即提交的 bounded streaming。
暂不需要 Ray、Slurm 或分布式数据库。

## 优先级路线图

### P0：先让结论可信

1. Slow Loop 改成真实的等预算配对 replay；完成前默认关闭。
2. 统一选择策略 contract，修复 `parent_selector` 配置与运行时不一致，并
   记录每次选择 trace。
3. 扩展 run bundle provenance，增加 `omnievolve research replay <run-id>`
   的严格校验模式。
4. 完成三任务 pilot，公开所有成功、失败和无效 run。
5. 给每个 benchmark 加 private/hidden 测试和 evaluator mutation tests。

P0 验收标准：

- 同一 run bundle 在同一环境中能复现非 LLM 阶段结果；
- provider/model 不可完全确定时，报告明确标为 stochastic replay；
- Slow Loop promotion 的 challenger score 不再来自 champion 历史；
- 配置中每个启用的选择机制都能在 trace 中看到，未知配置启动即失败；
- pilot 报告包含方差、CI、效应量、失败率、token、成本和墙钟。

### P1：用实验选择搜索机制

1. 引入最小 QD archive 和任务行为描述符。
2. 把 point/crossover/rewrite/diff/repair 做成 operator portfolio，用
   Thompson sampling 或 UCB 按任务和阶段调度。
3. reference credit 改为增益与 adopted-reference 加权。
4. 加入 successive halving：静态检查、小样本、完整 benchmark、多次复测。
5. 实现多文件 `ChangePlan` 和符号图驱动 patch/repair。
6. 增加 EoH 风格的 `thought+code vs code-only` 消融，以及 Vesper 风格的
   `many-shallow vs few-deep` matched-token 消融。

### P2：只有 P0/P1 有显著结果后再做

- DGM/Meta-Harness 风格的 agent/harness 源码自修改；
- PACEvolve++/ThetaEvolve 风格的 test-time RL；
- 跨机器调度、Slurm、GPU 大规模 QD；
- 跨语言统一语义 IR。

## 应主动避免的工程方向

- **不要把 Git 改回默认后端。** CAS 更适合单机高频候选、去重和不可变
  artifact；Git 可保留给人工审阅、worktree agent 和导出。
- **不要再新增 selector 或 novelty heuristic。** 先统一已有控制面并消融。
- **不要把“多文件存储”宣传为“仓库级语义进化”。** 两者尚有明显距离。
- **不要以测试数量替代研究证据。** 单元测试证明实现契约，不证明搜索收益。
- **不要直接跑更大的矩阵来掩盖高方差。** 先 pilot、估计方差和功效。
- **不要把当前 Slow Loop 称作 DGM 式自修改。** 它目前是受控策略参数与
  prompt 变异，而且 challenger 评估仍需修复。

## 推荐定位

短期最准确的项目描述是：

> OmniEvolve is a single-machine, evaluator-driven research harness for
> reproducible program evolution, with graph-guided search, content-addressed
> artifacts, and fail-closed evaluation.

下一版本的主目标应叫 **Evidence-First Release**，而不是继续强调更多 evolve
mechanism。只要 Slow Loop canary、选择 contract、完整 provenance 和三任务
pilot 做扎实，OmniEvolve 就会从“功能丰富的实现”跨到“可以严肃比较的研究框架”。
