# OmniEvolve v0.2 Alpha 发布说明

**发布日期：** 2026-07-20
**版本：** v0.2 Alpha

## 概述

OmniEvolve v0.2 是受控元进化框架的 Alpha 版本。它结合 MCTS 搜索、分层记忆、多级新颖性门和受控元进化（Slow Loop），支持任意领域的程序自动优化。

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
- kill-9 恢复（租约过期任务自动重新入队）
- 配置快照与秘密遮蔽

### 元进化
- SearchPolicyGenome（14 个可进化参数）
- Champion-Challenger 模式 + 原子回滚
- L0/L1/L2 风险分级 + Replay/Canary 验证
- 角色条件化非平稳 Bandit 路由（Sliding-window UCB / Discounted UCB）

### CLI
- `run` / `resume` / `status` / `best` / `export` / `policy` / `audit` / `recover` / `doctor`

### 文献模式集成
- Inspiration programs（ShinkaEvolve/AlphaEvolve）
- Meta-scratchpad（ShinkaEvolve）
- Agent retry/backoff/fallback
- 结构化输出修复

## 安装

```bash
# Core（零外部依赖）
pip install -e "."

# 向量检索增强
pip install -e ".[vector]"
pip install -e ".[local-embed]"

# Docker 沙箱
pip install -e ".[docker]"

# 全量
pip install -e ".[vector,local-embed,docker,viz,tuning]"
```

## 快速开始

```bash
cp configs/omnievolve.toml.example omnievolve.toml
omnievolve run ./my_code.py -e my_evaluator:MyEvaluator --gens 30
```

参见 `examples/python_optimization/` 获取完整示例。

## 测试

```
180 tests passed
15 P0 quality gate tests passed
ruff: All checks passed
```

## 已知限制

1. **需要 LLM API Key**：无 key 时候选生成失败（初始候选仍可评估）
2. **Docker 推荐**：TrustedSubprocessBackend 不提供安全隔离
3. **zvec 可选**：默认使用 NumPy 精确检索（足够小规模）
4. **单机**：不支持分布式执行（v0.2 scope）
5. **评估器噪声**：高噪声评估器会使健康指标失真

## 不在 v0.2 范围

- 完整 MCTS rollout（v0.2 只做 Progressive MCGS）
- 无限制自修改评估器（L2 永久禁止）
- 多语言支持（v0.2 聚焦 Python）
- GUI 仪表盘（CLI 可用）
- 分布式执行

## 参考系统

- AlphaEvolve (Google DeepMind) — 进化管线架构
- ShinkaEvolve (Sakana AI) — 样本效率优化
- DGM (ICLR 2026) — 开放式自改进
- OpenEvolve — 开源 AlphaEvolve 复现
