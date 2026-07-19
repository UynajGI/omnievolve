# 范围基线与砍 Scope 建议

## 1. v0.2 Alpha 必须包含

- SQLite v0.2 schema、迁移、事务与完整性约束。
- SHA-256 内容寻址 Artifact Store。
- DockerBackend 默认隔离；TrustedSubprocessBackend 显式开启。
- TaskEvaluator `build_plan()` / `parse_result()` 与 Evaluator Registry。
- Candidate、Thought、Lineage、EvaluationRun、SearchState、Job Lease。
- Director、Coder、Critic 与 PromptVersion、调用账本、预算门。
- EmbeddingProfile、VectorBackend、NumPy fallback、zvec Adapter、Outbox。
- FTS5 + 向量混合检索、L0–L4 分层记忆。
- Embedding + AST + Behavior 的多级 NoveltyGate。
- 基础岛屿搜索、迁移、跨分支融合、轻量 Progressive MCGS。
- TelemetryAggregator、HealthPolicy、四类健康指标。
- 角色条件化 Sliding-window UCB。
- SearchPolicyGenome、Champion/Challenger、L0 自适应、回滚。
- CLI：run/resume/status/best/export/audit/doctor。

## 2. 默认砍掉或延期

| 项目 | v0.2 决策 | 原因 | 重新进入条件 |
|---|---|---|---|
| 完整 UCT/MCTS rollout | 延期 | 基础状态与奖励未稳定，容易做成伪 MCTS | S7 轻量 MCGS 显示明确瓶颈 |
| Prompt Challenger 自动晋升 | Phase 4 | 属于 L1，需要 Replay/Canary 统计 | L0 策略版本与回滚稳定 |
| Agent 自修改 | Phase 4 | 高风险、难审计 | Governance 与 replay 完整 |
| Harness 自重写 | 不做 | 破坏评估主权与可信度 | 仅允许非语义基础设施适配 |
| 自动修改评分/测试/hidden set | 永久禁止 | Reward hacking | 无 |
| Neo4j/Milvus 默认部署 | 不做 | 违背 local-first，增加运维 | 单机规模达到证据阈值 |
| 全语言支持 | 只做 Python | 沙箱、AST、构建链复杂度爆炸 | Python E2E 稳定后逐语言插件化 |
| HardenedBackend 全实现 | Adapter 占位 | 工程与平台成本高 | 有明确高安全用户或云部署需求 |
| 大规模跨任务全局记忆 | 延期 | 污染、权限和可解释性风险 | L0–L3 作用域和消融通过 |
| Bayesian/Advisor 学习 | Phase 4 | 数据量不足前只会过拟合 | 有足够 PolicyExperiment 数据 |
| GUI Dashboard | 不做 | CLI/导出先满足审计 | Alpha 后用户需求验证 |

## 3. 可选进一步压缩版本

### 最小可信 MVP（约 22–30 人日）

保留 S1–S5、S9 的基础 CLI；S6 只做 NumPy fallback；S7 只做 L0/L1 记忆和 Embedding+AST 新颖性；S8 只记录 telemetry 不自动调参；不做 zvec、岛屿搜索、行为签名和 L0 policy mutator。

### 比赛演示版（不建议冒充 Alpha）

保留一个 demo evaluator、DockerBackend、Candidate loop、三 Agent、基础记忆和可视化导出。必须明确缺少 500 候选 soak、完整恢复、索引 reconcile 与策略治理。

## 4. 不能砍的安全与可信性 scope

以下项目即使延误也不能删：

- 默认隔离执行；
- 评估语义不可变；
- EvaluationRun 幂等提交；
- Artifact 与版本 provenance；
- kill -9 恢复；
- secret/redaction；
- L2 禁止规则；
- 发布前 E2E 与故障注入。
