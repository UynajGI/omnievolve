# Phase 4：受控元进化 Backlog

> 本文件不是 v0.2 Alpha 承诺范围。只有 M5 通过并积累足够运行数据后才进入。

## Epic P4-1：Prompt Challenger + Replay/Canary

- P4-01 PromptGenome 与语义 diff。
- P4-02 Prompt challenger 生成器。
- P4-03 固定历史窗口离线 replay。
- P4-04 等预算比较、置信区间与晋升阈值。
- P4-05 小流量 canary 与自动回滚。
- P4-06 污染/泄露/过拟合审计。

## Epic P4-2：L1 搜索控制器进化

- P4-07 context pruning policy 版本化。
- P4-08 crossover/backtracking 策略 challenger。
- P4-09 selector/novelty/router 联合策略实验。
- P4-10 搜索控制器代码修改的构建、测试和 sandbox 验证。

## Epic P4-3：Evaluation Infrastructure Adaptation

只允许非语义变化：timeout schedule、build cache、benchmark repetitions、资源分配、编译 flags、结果采集。

- P4-11 Environment challenger。
- P4-12 baseline 与 elite 全量重跑。
- P4-13 排名稳定性检验。
- P4-14 不稳定自动拒绝与回滚。

## Epic P4-4：Bayesian / Advisor Learning

- P4-15 PolicyExperiment 数据集与特征定义。
- P4-16 离线 contextual bandit baseline。
- P4-17 Bayesian optimizer 对照。
- P4-18 Advisor model 训练/评估。
- P4-19 与规则/Sliding UCB 等预算比较。

## Epic P4-5：Agent 代码自修改

- P4-20 Agent source artifact 与 build manifest。
- P4-21 自修改 patch 生成与静态安全扫描。
- P4-22 完整 regression + held-out task replay。
- P4-23 Champion/Challenger 晋升和紧急熔断。

## 永久禁止

- 修改任务正确性定义、隐藏测试、评分公式或聚合规则。
- 为特定候选添加特殊评分逻辑。
- 绕过 Sandbox 执行候选或自修改代码。
- 未经 Replay/Canary 直接替换 Champion。
