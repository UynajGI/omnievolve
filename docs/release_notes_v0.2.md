# OmniEvolve v0.2 发布说明

**版本：** v0.2.0-beta
**状态：** Beta

## 概述

OmniEvolve v0.2 是受控元进化框架 (Controlled Meta-Evolution Framework) 的 Beta 版本。它结合 MCTS 搜索、分层记忆、多级新颖性门和受控元进化（Slow Loop），支持任意领域的程序自动优化。Local-first 设计，零外部服务依赖即可运行。

## 主要特性

### 双循环架构
- **Fast Loop**：单代候选进化 11 步（Router → MCTS 父代选择 → 交叉/变异 → Director → NoveltyGate → Coder → Critic 重试 → ArtifactStore → TaskEvaluator → Sandbox → 全状态更新）
- **Slow Loop**：策略窗口评估与受控元进化（Telemetry → Health → MetaPlanner → Governance L0/L1/L2 → Challenger → Replay → Promote/Reject）

### 搜索引擎
- 渐进式 MCGS（MCTS 变体），支持虚拟损失和 PUCT
- 岛屿模型 + 周期性迁移 + 停滞检测
- 多父代跨分支融合（segment / function-level / feature-merge）
- 多级新颖性门（Embedding → AST → 行为签名 → 可选 LLM 判断）

### 记忆与检索
- 分层记忆 L0-L4（分支 → 实验 → 任务族 → 领域 → 全局）
- 向量 Outbox 最终一致性（SQLite ↔ zvec/NumPy）
- 混合检索（FTS5 + 向量召回 + scope filter）
- 记忆引用/采用/结果追踪

### 安全与可信
- DockerBackend 默认安全（禁网/只读根/降权/no_new_privileges）
- 评估语义不可变（L2 永久禁止修改任务语义）
- 内容寻址 Artifact Store（SHA-256 去重/校验/复现）
- 可插拔代码存储后端（CAS / Git；当前默认 CAS，Git 提供原生 ancestry DAG）
- kill-9 恢复（租约过期任务自动重新入队）
- 配置快照与秘密遮蔽

### 元进化
- SearchPolicyGenome（可进化参数集）
- Champion-Challenger 模式 + 原子回滚
- L0/L1/L2 风险分级 + Replay/Canary 验证
- 角色条件化非平稳 Bandit 路由（Sliding-window UCB / Discounted UCB）
- 贝叶斯超参调优（GP + EI 采集函数）
- Prompt 自动进化（PromptEvolver，受 Champion-Challenger 治理）

### 韧性
- 熔断器（3 态断路器：CLOSED → OPEN → HALF_OPEN）
- 令牌桶速率限制器
- 每代自动检查点恢复
- SQLite WAL 并发模型（多线程读写压力测试通过）

### 评估失败反馈闭环（P0-1）
- Evaluator 的 stderr / failure_reason 自动回流到 Coder Prompt
- Coder 据此修复根因而非重复相同错误
- 效果：sort 5 代通过率 19% → 57%（3 倍提升）

### CLI
- `run` / `status` / `best` / `export` / `policy` / `audit` / `recover` / `migrate` / `doctor`
- `--resume` 断点续跑，`--no-self-evolve` 仅 Fast Loop，`--trusted` 非隔离模式

### 文献模式集成
- Inspiration programs（ShinkaEvolve/AlphaEvolve 模式：高分+随机样本）
- Meta-scratchpad（ShinkaEvolve：跨代失败方向追踪）
- Agent retry/backoff/fallback（熔断器 + 令牌桶）
- 结构化输出修复（JSON → 代码块提取 → 字段提取 → 裸代码回退）

## 安装

```bash
# Core（零外部依赖）
pip install -e "."

# 向量检索增强
pip install -e ".[vector]"
pip install -e ".[local-embed]"

# Docker / Monty 沙箱
pip install -e ".[docker]"
pip install -e ".[monty]"

# 全量
pip install -e ".[all]"
```

可用的安装档：`vector`、`local-embed`、`docker`、`monty`、`viz`、`tuning`、`profile`、`all`。

## 快速开始

```bash
cp configs/omnievolve.toml.example omnievolve.toml
omnievolve run ./my_code.py -e my_evaluator:MyEvaluator --gens 30 --trusted
```

完整示例参见 `examples/` 目录（`python_optimization`、`circle_packing`、`heilbronn`、`matmul`）。

## 测试

采用分层测试策略（Tier 1 CI → Tier 2 smoke → Tier 3 手动），避免每次测试都消耗 API 配额：

```bash
make test          # Tier 1: 快速单元测试（FakeLLM，CI 默认）
make test-cov      # Tier 1 + 覆盖率
make test-llm      # Tier 2: LLM 烟雾测试（2-3 代真实进化，需 API key）
make test-slow     # 慢速/集成测试（Docker、soak 50 代）
```

- **Tier 1**：FakeLLM 驱动，覆盖全部逻辑路径，CI 默认运行
- **Tier 2**：真实 LLM API 调用，2-3 代烟雾测试验证管线连通性，需手动运行
- **Tier 3**：手动 soak 测试（50 代稳定性）和 Docker 集成测试

代码质量：ruff（0 errors）+ mypy clean。

## 已知限制

1. **需要 LLM API Key**：无 key 时候选生成失败（初始候选仍可评估）
2. **Docker 推荐**：TrustedSubprocessBackend 不提供安全隔离，生产环境推荐 DockerBackend
3. **zvec 可选**：默认使用 NumPy 精确检索（小规模足够，百万级向量建议装 zvec）
4. **单机**：不支持分布式执行（v0.2 scope）
5. **评估器噪声**：高噪声评估器会使健康指标失真

## 不在 v0.2 范围

- 完整 MCTS rollout（v0.2 只做 Progressive MCGS）
- 无限制自修改评估器（L2 永久禁止）
- 多语言支持（v0.2 聚焦 Python）
- GUI 仪表盘（CLI 可用，Prometheus/OpenTelemetry 可选）
- 分布式执行

## 参考系统

OmniEvolve 吸收了以下系统的设计理念：

- [AlphaEvolve](https://github.com/codelion/openevolve) (Google DeepMind) — SEARCH/REPLACE diff、EVOLVE-BLOCK、Rich Prompt、PromptEvolver
- [ShinkaEvolve](https://github.com/Nevergoodenough/ShinkaEvolve) (Sakana AI) — Power law/weighted 采样、Meta-scratchpad、Bandit relative reward
- [MLEvolve](https://github.com/codelion/mlevolve) — Reference edges、Progressive exploration schedule
- [OpenEvolve](https://github.com/codelion/openevolve) — 开源 AlphaEvolve 复现
- [DGM](https://github.com/codelion/dgm) — Darwin Gödel Machine，开放式自改进
