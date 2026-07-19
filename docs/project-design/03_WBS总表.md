# WBS 总表

## 字段说明

- **依赖**：必须完成后才能进入 `Ready` 的任务；`—` 表示无前置任务。
- **模型等级**：A=高级模型/架构复核，B=标准代码模型，C=轻量模型，T=确定性工具。
- **可并行**：“可”表示依赖完成后可与同 Sprint 其他任务并行；“否”通常位于关键路径或承担集成职责。

| Task ID | Phase | Sprint | 任务 | 依赖 | Owner | 模型 | 估算 | 可并行 |
|---|---|---|---|---|---|---|---:|---|
| S1-01 | Phase 1 | S1 | 冻结核心实体与不变量 | — | 架构负责人 / 高级模型 | A | 6h | 否 |
| S1-02 | Phase 1 | S1 | 建立数据库连接与 PRAGMA 策略 | S1-01 | 核心工程实现 | B | 3h | 可 |
| S1-03 | Phase 1 | S1 | 实现 schema_version 与迁移框架 | S1-02 | 核心工程实现 | B | 6h | 可 |
| S1-04 | Phase 1 | S1 | 实现 experiment/task/domain 作用域表 | S1-01,S1-03 | 核心工程实现 | B | 4h | 可 |
| S1-05 | Phase 1 | S1 | 实现 artifact 元数据表与引用计数策略 | S1-01,S1-03 | 核心工程实现 | B | 5h | 可 |
| S1-06 | Phase 1 | S1 | 实现 SHA-256 内容寻址与原子写入 | S1-05 | 核心工程实现 | B | 7h | 否 |
| S1-07 | Phase 1 | S1 | 实现 Artifact Manifest 与 MIME/类型登记 | S1-06 | 核心工程实现 | C | 4h | 可 |
| S1-08 | Phase 1 | S1 | 实现 Unit of Work / 事务封装 | S1-02,S1-03 | 架构负责人 / 高级模型 | A | 6h | 否 |
| S1-09 | Phase 1 | S1 | 实现 Repository 基础协议 | S1-08 | 核心工程实现 | B | 5h | 可 |
| S1-10 | Phase 1 | S1 | 创建 Candidate/Lineage/Evaluation/Policy 等 v0.2 表 | S1-01,S1-03 | 核心工程实现 | A | 8h | 否 |
| S1-11 | Phase 1 | S1 | 创建 job lease、outbox、prompt、memory、telemetry 表 | S1-10 | 核心工程实现 | B | 7h | 可 |
| S1-12 | Phase 1 | S1 | 配置 SQLite FTS5 能力检测与降级 | S1-02 | 核心工程实现 | C | 3h | 可 |
| S1-13 | Phase 1 | S1 | 实现数据库完整性与约束测试 | S1-10,S1-11 | 测试与质量 | C | 6h | 可 |
| S1-14 | Phase 1 | S1 | 实现 WAL 并发与锁竞争测试 | S1-02,S1-08 | 测试与质量 | B | 5h | 可 |
| S1-15 | Phase 1 | S1 | 实现 Artifact 去重、损坏检测与恢复测试 | S1-06,S1-07 | 测试与质量 | B | 6h | 可 |
| S1-16 | Phase 1 | S1 | 编写存储 ADR 与运维诊断说明 | S1-01~S1-15 | 文档与发布 | C | 4h | 可 |
| S2-01 | Phase 1 | S2 | 冻结 SandboxBackend 协议与数据结构 | S1-01 | 安全与沙箱 | A | 6h | 否 |
| S2-02 | Phase 1 | S2 | 定义 ExecutionEnvironmentVersion 规范 | S1-10,S2-01 | 安全与沙箱 | A | 6h | 可 |
| S2-03 | Phase 1 | S2 | 实现 DockerBackend 最小执行路径 | S2-01 | 安全与沙箱 | B | 8h | 否 |
| S2-04 | Phase 1 | S2 | 实现默认禁网与 DNS 隔离 | S2-03 | 安全与沙箱 | B | 5h | 可 |
| S2-05 | Phase 1 | S2 | 实现只读根文件系统与最小可写 tmpfs | S2-03 | 安全与沙箱 | B | 5h | 可 |
| S2-06 | Phase 1 | S2 | 实现非 root、cap-drop、no-new-privileges | S2-03 | 安全与沙箱 | B | 4h | 可 |
| S2-07 | Phase 1 | S2 | 实现 CPU/内存/PID/磁盘/墙钟限制 | S2-03 | 安全与沙箱 | B | 7h | 否 |
| S2-08 | Phase 1 | S2 | 实现环境变量白名单与秘密脱敏 | S2-03 | 安全与沙箱 | A | 6h | 可 |
| S2-09 | Phase 1 | S2 | 实现只读数据集挂载与候选工作区 | S2-05 | 安全与沙箱 | B | 5h | 可 |
| S2-10 | Phase 1 | S2 | 实现 stdout/stderr 限流与截断 | S2-03 | 核心工程实现 | C | 4h | 可 |
| S2-11 | Phase 1 | S2 | 实现超时、取消与容器清理 | S2-07 | 安全与沙箱 | B | 6h | 否 |
| S2-12 | Phase 1 | S2 | 实现执行产物采集并写入 Artifact Store | S1-06,S2-03 | 核心工程实现 | B | 5h | 可 |
| S2-13 | Phase 1 | S2 | 实现 TrustedSubprocessBackend | S2-01 | 核心工程实现 | B | 5h | 可 |
| S2-14 | Phase 1 | S2 | 实现 Backend Registry 与 doctor 检测 | S2-03,S2-13 | 核心工程实现 | C | 4h | 可 |
| S2-15 | Phase 1 | S2 | 编写网络/秘密/路径穿越安全测试 | S2-04,S2-08,S2-09 | 测试与质量 | A | 8h | 可 |
| S2-16 | Phase 1 | S2 | 编写 fork bomb/内存/磁盘/超时压力测试 | S2-07,S2-11 | 测试与质量 | B | 8h | 可 |
| S2-17 | Phase 1 | S2 | 记录 Docker 安全基线与残余风险 | S2-01~S2-16 | 文档与发布 | A | 5h | 可 |
| S3-01 | Phase 1 | S3 | 冻结 EvaluationPlan/EvalOutput/EvaluationContext | S2-01 | 评估与实验 | A | 6h | 否 |
| S3-02 | Phase 1 | S3 | 实现 TaskEvaluator Protocol | S3-01 | 评估与实验 | B | 4h | 可 |
| S3-03 | Phase 1 | S3 | 实现 Evaluator Registry 与版本 digest | S1-10,S3-01 | 评估与实验 | A | 7h | 否 |
| S3-04 | Phase 1 | S3 | 实现任务语义不可变策略 | S3-03 | 评估与实验 | A | 6h | 可 |
| S3-05 | Phase 1 | S3 | 实现 EvaluationPlan 校验器 | S3-01,S2-09 | 安全与沙箱 | B | 5h | 可 |
| S3-06 | Phase 1 | S3 | 实现 EvaluationRun 状态机 | S1-10,S3-01 | 核心工程实现 | A | 7h | 否 |
| S3-07 | Phase 1 | S3 | 实现随机种子、重复次数与统计字段 | S3-06 | 评估与实验 | B | 5h | 可 |
| S3-08 | Phase 1 | S3 | 实现正确性门与性能评分解耦 | S3-02 | 评估与实验 | A | 5h | 可 |
| S3-09 | Phase 1 | S3 | 实现 Progressive Evaluation 阶段描述 | S3-01,S3-05 | 评估与实验 | B | 5h | 可 |
| S3-10 | Phase 1 | S3 | 实现 Python demo evaluator | S3-02,S3-05 | 评估与实验 | C | 6h | 可 |
| S3-11 | Phase 1 | S3 | 实现 baseline 登记与重跑 | S3-03,S3-06 | 评估与实验 | B | 5h | 可 |
| S3-12 | Phase 1 | S3 | 实现解析失败与异常分类 | S3-02,S3-06 | 评估与实验 | C | 4h | 可 |
| S3-13 | Phase 1 | S3 | 实现 evaluator 不可越权测试 | S3-04,S3-05 | 测试与质量 | A | 7h | 可 |
| S3-14 | Phase 1 | S3 | 实现 EvaluationRun 复现测试 | S3-06,S3-07,S3-10 | 测试与质量 | B | 7h | 可 |
| S3-15 | Phase 1 | S3 | 编写评估器开发指南 | S3-01~S3-14 | 文档与发布 | C | 4h | 可 |
| S4-01 | Phase 1 | S4 | 实现 Candidate/Thought Repository | S1-09,S1-10 | 核心工程实现 | B | 6h | 可 |
| S4-02 | Phase 1 | S4 | 实现多父代 CandidateLineage | S1-10 | 核心工程实现 | A | 6h | 可 |
| S4-03 | Phase 1 | S4 | 实现 reference edge 与 lineage edge 分离 | S4-02 | 核心工程实现 | A | 4h | 可 |
| S4-04 | Phase 1 | S4 | 实现 SearchState 最小字段与更新规则 | S1-10,S4-01 | 搜索、记忆与元进化 | A | 7h | 否 |
| S4-05 | Phase 1 | S4 | 实现 Job Lease/Heartbeat/Expiry | S1-11 | 核心工程实现 | A | 8h | 否 |
| S4-06 | Phase 1 | S4 | 实现幂等键与结果提交协议 | S3-06,S4-05 | 核心工程实现 | A | 7h | 否 |
| S4-07 | Phase 1 | S4 | 实现基础 Scheduler 队列 | S4-05,S4-06 | 核心工程实现 | B | 8h | 否 |
| S4-08 | Phase 1 | S4 | 实现候选 Artifact materialize 与 diff apply | S1-06,S4-01 | 核心工程实现 | B | 6h | 可 |
| S4-09 | Phase 1 | S4 | 实现最小 ParentSelector（best/tournament/random） | S4-01,S4-04 | 搜索、记忆与元进化 | B | 5h | 可 |
| S4-10 | Phase 1 | S4 | 实现基础 Mutation Registry 占位 | S4-08 | 搜索、记忆与元进化 | C | 4h | 可 |
| S4-11 | Phase 1 | S4 | 串联 Sandbox 与 TaskEvaluator | S2-12,S3-06,S4-07 | 核心工程实现 | A | 8h | 否 |
| S4-12 | Phase 1 | S4 | 实现 best/elite archive 最小逻辑 | S4-01,S3-08 | 搜索、记忆与元进化 | B | 5h | 可 |
| S4-13 | Phase 1 | S4 | 实现 resume 与 orphan job recovery | S4-05,S4-07 | 核心工程实现 | A | 7h | 否 |
| S4-14 | Phase 1 | S4 | 实现基础 GraphStore 与子图加载 | S4-02,S4-03 | 核心工程实现 | B | 6h | 可 |
| S4-15 | Phase 1 | S4 | 实现 500 候选 soak 测试 | S4-07~S4-13 | 测试与质量 | A | 10h | 否 |
| S4-16 | Phase 1 | S4 | 实现 kill -9/进程崩溃故障注入 | S4-13 | 测试与质量 | A | 9h | 可 |
| S4-17 | Phase 1 | S4 | 输出 Phase 1 审计报告 | S1~S4 | 文档与发布 | A | 5h | 否 |
| S5-01 | Phase 2 | S5 | 冻结 AgentContext/ThoughtOutput/CodeOutput | S4-01,S4-07 | 架构负责人 / 高级模型 | A | 6h | 否 |
| S5-02 | Phase 2 | S5 | 实现 ModelGateway/LiteLLM Adapter | S5-01 | 核心工程实现 | B | 7h | 否 |
| S5-03 | Phase 2 | S5 | 实现 LLMCallLedger | S1-10,S5-02 | 核心工程实现 | A | 6h | 可 |
| S5-04 | Phase 2 | S5 | 实现 PromptVersion Repository | S1-10 | 核心工程实现 | B | 5h | 可 |
| S5-05 | Phase 2 | S5 | 实现 ContextBuilder 与 token budget | S5-01,S5-04 | 搜索、记忆与元进化 | A | 7h | 否 |
| S5-06 | Phase 2 | S5 | 实现 DirectorAgent 最小版本 | S5-02,S5-05 | 搜索、记忆与元进化 | B | 6h | 可 |
| S5-07 | Phase 2 | S5 | 实现 CoderAgent diff/full rewrite | S5-02,S5-05 | 核心工程实现 | B | 7h | 可 |
| S5-08 | Phase 2 | S5 | 实现 CriticAgent 静态审查 | S5-02,S5-05 | 核心工程实现 | B | 6h | 可 |
| S5-09 | Phase 2 | S5 | 实现结构化输出校验与 repair | S5-06~S5-08 | 核心工程实现 | B | 5h | 可 |
| S5-10 | Phase 2 | S5 | 实现 Agent retry/backoff/fallback | S5-02,S5-09 | 核心工程实现 | B | 5h | 可 |
| S5-11 | Phase 2 | S5 | 实现基础静态模型路由占位 | S5-02 | 搜索、记忆与元进化 | C | 3h | 可 |
| S5-12 | Phase 2 | S5 | 实现 token/费用预算硬门 | S5-03,S5-10 | 核心工程实现 | A | 5h | 可 |
| S5-13 | Phase 2 | S5 | 接入 Scheduler 生成链路 | S4-07,S5-06~S5-12 | 核心工程实现 | A | 8h | 否 |
| S5-14 | Phase 2 | S5 | 使用 FakeLLM 编写确定性单测 | S5-06~S5-10 | 测试与质量 | C | 7h | 可 |
| S5-15 | Phase 2 | S5 | 实现真实模型 smoke test（可选密钥） | S5-13 | 测试与质量 | B | 4h | 可 |
| S5-16 | Phase 2 | S5 | 编写 Prompt 与 Agent 开发指南 | S5-01~S5-15 | 文档与发布 | C | 4h | 可 |
| S6-01 | Phase 2 | S6 | 冻结 EmbeddingProfile 数据模型 | S1-10 | 搜索、记忆与元进化 | A | 6h | 否 |
| S6-02 | Phase 2 | S6 | 实现 Embedder Protocol 与 fake embedder | S6-01 | 搜索、记忆与元进化 | B | 5h | 可 |
| S6-03 | Phase 2 | S6 | 实现 API 文本/代码 Embedder Adapter | S6-02 | 搜索、记忆与元进化 | B | 7h | 可 |
| S6-04 | Phase 2 | S6 | 实现本地 sentence-transformers Adapter | S6-02 | 搜索、记忆与元进化 | B | 6h | 可 |
| S6-05 | Phase 2 | S6 | 冻结 VectorBackend Protocol | S6-01 | 搜索、记忆与元进化 | A | 5h | 可 |
| S6-06 | Phase 2 | S6 | 实现 NumPy 精确检索 fallback | S6-05 | 搜索、记忆与元进化 | B | 6h | 可 |
| S6-07 | Phase 2 | S6 | 实现 zvec Adapter 与 collection lifecycle | S6-05 | 搜索、记忆与元进化 | A | 8h | 否 |
| S6-08 | Phase 2 | S6 | 实现 vector_index_outbox 生产端 | S1-11,S4-01 | 核心工程实现 | B | 5h | 可 |
| S6-09 | Phase 2 | S6 | 实现 Outbox Indexer 与幂等消费 | S6-07,S6-08 | 搜索、记忆与元进化 | A | 8h | 否 |
| S6-10 | Phase 2 | S6 | 实现索引修复与 reconcile | S6-09 | 搜索、记忆与元进化 | A | 7h | 可 |
| S6-11 | Phase 2 | S6 | 实现 FTS5 文档与作用域索引 | S1-12 | 搜索、记忆与元进化 | B | 6h | 可 |
| S6-12 | Phase 2 | S6 | 实现 Hybrid Retriever 与融合排序 | S6-06,S6-07,S6-11 | 搜索、记忆与元进化 | A | 8h | 否 |
| S6-13 | Phase 2 | S6 | 实现 code/thought 独立索引与元数据过滤 | S6-12 | 搜索、记忆与元进化 | B | 5h | 可 |
| S6-14 | Phase 2 | S6 | 实现 profile 迁移/重建流程 | S6-09,S6-10 | 搜索、记忆与元进化 | A | 7h | 可 |
| S6-15 | Phase 2 | S6 | 编写 zvec vs NumPy 一致性测试 | S6-06,S6-07 | 测试与质量 | B | 6h | 可 |
| S6-16 | Phase 2 | S6 | 编写 outbox 崩溃恢复测试 | S6-09,S6-10 | 测试与质量 | A | 7h | 可 |
| S6-17 | Phase 2 | S6 | 编写向量配置与迁移文档 | S6-01~S6-16 | 文档与发布 | C | 4h | 可 |
| S7-01 | Phase 2 | S7 | 冻结 MemoryRecord 与 L0~L4 scope 规则 | S1-10,S6-12 | 搜索、记忆与元进化 | A | 6h | 否 |
| S7-02 | Phase 2 | S7 | 实现 Memory Ingestor 与四元组扩展 | S7-01,S4-12 | 搜索、记忆与元进化 | B | 7h | 可 |
| S7-03 | Phase 2 | S7 | 实现分层检索预算与去重 | S6-12,S7-01 | 搜索、记忆与元进化 | A | 7h | 否 |
| S7-04 | Phase 2 | S7 | 实现记忆 citation/adoption/outcome 追踪 | S5-05,S7-03 | 搜索、记忆与元进化 | B | 6h | 可 |
| S7-05 | Phase 2 | S7 | 实现 Embedding 新颖性预筛 | S6-12 | 搜索、记忆与元进化 | B | 5h | 可 |
| S7-06 | Phase 2 | S7 | 实现 AST/结构签名 | S4-08 | 搜索、记忆与元进化 | B | 7h | 可 |
| S7-07 | Phase 2 | S7 | 实现行为签名接口与 demo | S3-06,S4-11 | 评估与实验 | A | 7h | 可 |
| S7-08 | Phase 2 | S7 | 实现多级 NoveltyGate 决策器 | S7-05,S7-06,S7-07 | 搜索、记忆与元进化 | A | 8h | 否 |
| S7-09 | Phase 2 | S7 | 实现可选 LLM novelty judge | S5-02,S7-08 | 搜索、记忆与元进化 | B | 5h | 可 |
| S7-10 | Phase 2 | S7 | 实现 IslandState 与岛内 archive | S4-04,S4-12 | 搜索、记忆与元进化 | A | 7h | 否 |
| S7-11 | Phase 2 | S7 | 实现岛间迁移策略 | S7-10 | 搜索、记忆与元进化 | B | 6h | 可 |
| S7-12 | Phase 2 | S7 | 实现 Crossover 多父代选择 | S4-02,S7-10 | 搜索、记忆与元进化 | A | 7h | 可 |
| S7-13 | Phase 2 | S7 | 实现 Mutation Operator Registry | S4-10,S5-07 | 搜索、记忆与元进化 | B | 6h | 可 |
| S7-14 | Phase 2 | S7 | 实现停滞检测与跨分支触发 | S7-10,S7-12 | 搜索、记忆与元进化 | A | 6h | 可 |
| S7-15 | Phase 2 | S7 | 实现轻量 Progressive MCGS 占位 | S4-04,S7-10 | 搜索、记忆与元进化 | A | 8h | 否 |
| S7-16 | Phase 2 | S7 | 实现记忆/新颖性消融测试框架 | S7-03,S7-08 | 测试与质量 | A | 8h | 可 |
| S7-17 | Phase 2 | S7 | 实现 false rejection 回归集 | S7-08 | 测试与质量 | B | 7h | 可 |
| S7-18 | Phase 2 | S7 | 输出 Phase 2 验收报告 | S5~S7 | 文档与发布 | A | 5h | 否 |
| S8-01 | Phase 3 | S8 | 冻结 Telemetry Event Schema | S4-07,S5-03,S7-04 | 评估与实验 | A | 7h | 否 |
| S8-02 | Phase 3 | S8 | 实现事件采集与批量持久化 | S1-10,S8-01 | 评估与实验 | B | 6h | 可 |
| S8-03 | Phase 3 | S8 | 实现 MetaEvaluationWindow 切片 | S8-02 | 评估与实验 | A | 6h | 可 |
| S8-04 | Phase 3 | S8 | 实现成本归一化 ROI | S8-03 | 评估与实验 | A | 8h | 否 |
| S8-05 | Phase 3 | S8 | 实现搜索覆盖率指标 | S6-12,S8-03 | 评估与实验 | A | 8h | 可 |
| S8-06 | Phase 3 | S8 | 实现记忆有效性指标 | S7-04,S7-16,S8-03 | 评估与实验 | A | 7h | 可 |
| S8-07 | Phase 3 | S8 | 实现上下文污染指标 | S5-05,S7-04,S8-03 | 评估与实验 | A | 7h | 可 |
| S8-08 | Phase 3 | S8 | 实现 TelemetryAggregator | S8-04~S8-07 | 评估与实验 | B | 6h | 否 |
| S8-09 | Phase 3 | S8 | 实现 HealthPolicy 规则与迟滞 | S8-08 | 评估与实验 | A | 7h | 否 |
| S8-10 | Phase 3 | S8 | 实现 MetaPlanner 只读诊断 | S5-02,S8-09 | 搜索、记忆与元进化 | B | 6h | 可 |
| S8-11 | Phase 3 | S8 | 冻结 RoleConditionalRouter 接口 | S5-11,S8-03 | 搜索、记忆与元进化 | A | 5h | 可 |
| S8-12 | Phase 3 | S8 | 实现 Sliding-window UCB | S8-11 | 搜索、记忆与元进化 | A | 7h | 可 |
| S8-13 | Phase 3 | S8 | 实现 Director/Coder/Critic 分离奖励 | S5-03,S8-12 | 搜索、记忆与元进化 | A | 8h | 否 |
| S8-14 | Phase 3 | S8 | 实现 budget-aware 路由约束 | S5-12,S8-12 | 搜索、记忆与元进化 | B | 5h | 可 |
| S8-15 | Phase 3 | S8 | 实现健康指标 dashboard 数据接口 | S8-08,S8-09 | 核心工程实现 | C | 5h | 可 |
| S8-16 | Phase 3 | S8 | 实现指标单调性/边界/噪声测试 | S8-04~S8-09 | 测试与质量 | A | 8h | 可 |
| S8-17 | Phase 3 | S8 | 实现路由离线 replay 测试 | S8-12~S8-14 | 测试与质量 | A | 8h | 可 |
| S8-18 | Phase 3 | S8 | 编写健康指标解释与限制 | S8-01~S8-17 | 文档与发布 | C | 5h | 可 |
| S9-01 | Phase 3 | S9 | 冻结 SearchPolicyGenome schema | S8-09 | 搜索、记忆与元进化 | A | 7h | 否 |
| S9-02 | Phase 3 | S9 | 实现 SearchPolicyVersion Repository | S1-10,S9-01 | 搜索、记忆与元进化 | B | 6h | 可 |
| S9-03 | Phase 3 | S9 | 实现 Policy Archive Champion/Challenger | S9-02 | 搜索、记忆与元进化 | A | 7h | 否 |
| S9-04 | Phase 3 | S9 | 实现 L0 风险动作白名单 | S8-10,S9-01 | 安全与沙箱 | A | 6h | 可 |
| S9-05 | Phase 3 | S9 | 实现 L1/L2 拒绝与审计门禁 | S9-04 | 安全与沙箱 | A | 6h | 可 |
| S9-06 | Phase 3 | S9 | 实现 L0 Policy Mutator | S9-03,S9-04 | 搜索、记忆与元进化 | B | 7h | 否 |
| S9-07 | Phase 3 | S9 | 实现策略应用与原子回滚 | S9-02,S9-06 | 搜索、记忆与元进化 | A | 8h | 否 |
| S9-08 | Phase 3 | S9 | 实现最小同预算 challenger 比较 | S8-03,S9-03 | 评估与实验 | A | 8h | 可 |
| S9-09 | Phase 3 | S9 | 实现 CLI run/resume/status/best | S4-13,S8-15,S9-07 | 核心工程实现 | B | 8h | 可 |
| S9-10 | Phase 3 | S9 | 实现 CLI export/audit/doctor | S2-14,S4-14,S8-15 | 核心工程实现 | B | 8h | 可 |
| S9-11 | Phase 3 | S9 | 实现配置快照、校验与秘密遮蔽 | S5-12,S9-09 | 核心工程实现 | A | 6h | 可 |
| S9-12 | Phase 3 | S9 | 实现 Champion 完整导出/导入 | S9-03,S9-10 | 搜索、记忆与元进化 | B | 6h | 可 |
| S9-13 | Phase 3 | S9 | 实现端到端审计报告生成 | S9-10,S9-12 | 文档与发布 | A | 7h | 可 |
| S9-14 | Phase 3 | S9 | 实现 v0.2 Alpha E2E 基准任务 | S1~S9 | 测试与质量 | A | 10h | 否 |
| S9-15 | Phase 3 | S9 | 执行 Phase 1 全量 500 候选回归 | S9-14 | 测试与质量 | A | 10h | 可 |
| S9-16 | Phase 3 | S9 | 完成 pyproject extras 与安装矩阵 | S2,S6,S9-09 | 文档与发布 | B | 6h | 可 |
| S9-17 | Phase 3 | S9 | 完成用户指南、架构图和发布说明 | S9-09~S9-16 | 文档与发布 | C | 7h | 可 |
| S9-18 | Phase 3 | S9 | 召开 v0.2 Alpha Go/No-Go | S9-14~S9-17 | 架构负责人 / 高级模型 | A | 4h | 否 |

## 汇总

- Sprint 数：9
- 任务总数：152
- A 级任务：70
- B 级任务：65
- C 级任务：17

详细交付物和验收标准见 `Sprint_Backlog/S*_*.md`。
