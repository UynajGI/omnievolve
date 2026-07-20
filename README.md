# OmniEvolve

**受控元进化框架 (Controlled Meta-Evolution Framework)**

OmniEvolve 是一个 LLM 驱动的代码进化优化框架，结合 MCTS 搜索、分层记忆、多级新颖性门和受控元进化（Slow Loop），支持任意领域的程序自动优化。

## 核心特性

- **双循环架构**：Fast Loop（单代候选进化 11 步）+ Slow Loop（策略窗口评估与受控元进化）
- **渐进式 MCGS 搜索**：MCTS 引导的父代选择，支持多父代交叉融合
- **岛屿模型**：多个独立精英档案，周期性迁移，停滞检测
- **多级新颖性门**：Embedding → AST 结构 → 行为签名 → 可选 LLM 判断
- **分层记忆 L0-L4**：分支级 → 实验级 → 任务族 → 领域 → 全局
- **双轨评估**：轨道 A（任务评估器，用户定义）+ 轨道 B（系统健康度，框架内置）
- **角色条件化路由**：Sliding-window UCB / Discounted UCB 模型路由
- **受控元进化**：L0/L1/L2 风险分级，Champion-Challenger 模式，原子回滚
- **内容寻址 Artifact**：SHA-256 去重、校验、复现
- **默认安全沙箱**：DockerBackend（禁网、只读根、降权、资源限制）
- **Local-first**：SQLite + 本地 Artifact Store + NumPy 精确检索（零外部依赖）

## 安装

```bash
# 核心（零外部服务依赖）
pip install -e .

# 向量检索增强
pip install -e ".[vector]"
pip install -e ".[local-embed]"

# Docker 沙箱
pip install -e ".[docker]"

# Monty 沙箱（Rust 实现，微秒级启动）
pip install -e ".[monty]"

# 全量
pip install -e ".[vector,local-embed,docker,monty,viz,tuning]"
```

## 快速开始

### 1. 创建配置

```bash
cp configs/omnievolve.toml.example omnievolve.toml
# 编辑模型名、路径、API key 等
```

### 2. 实现评估器

```python
# my_evaluator.py
from omnievolve.eval.task_evaluator import (
    CandidateArtifact, EvalOutput, EvaluationContext,
    EvaluationPlan, CommandSpec, SandboxExecutionResult,
)

class MyEvaluator:
    version_id = "my-evaluator@1.0.0"

    def build_plan(self, candidate, context):
        return EvaluationPlan(
            commands=[CommandSpec(argv=["python", "-m", "pytest", "-v"])],
        )

    def parse_result(self, result, context):
        ok = result.return_codes and result.return_codes[0] == 0
        return EvalOutput(
            score=1.0 if ok else 0.0,
            metrics={},
            passed=ok,
        )

    def get_baseline(self):
        return 0.5
```

### 3. 运行进化

```bash
# 本地模式（默认，无需 Docker）
omnievolve run ./initial_code.py \
    --evaluator my_evaluator:MyEvaluator \
    --config omnievolve.toml \
    --gens 30

# Docker 安全模式（需 Docker daemon）
omnievolve run ./initial_code.py \
    --evaluator my_evaluator:MyEvaluator \
    --config omnievolve.toml \
    --gens 30
# (配置文件中 sandbox.backend = "docker")

# Monty 安全模式（Rust 沙箱，微秒级启动，需 pip install omnievolve[monty]）
omnievolve run ./initial_code.py \
    --evaluator my_evaluator:MyEvaluator \
    --config omnievolve.toml \
    --gens 30
# (配置文件中 sandbox.backend = "monty")

# 断点续跑
omnievolve run ./initial_code.py \
    --evaluator my_evaluator:MyEvaluator \
    --resume exp_a3f8c2
```

### 4. 查看结果

```bash
omnievolve status exp_a3f8c2      # 进度、Champion Policy、Top 候选
omnievolve best exp_a3f8c2 --code # 最优候选完整源码
omnievolve policy exp_a3f8c2      # Champion/Challenger 策略谱系
omnievolve audit exp_a3f8c2       # 端到端审计报告
omnievolve export exp_a3f8c2      # 导出 GraphML
omnievolve recover exp_a3f8c2     # 扫描租约/Outbox/孤立 Artifact
omnievolve doctor                 # 环境检测
```

## 架构

```
omnievolve/
├── storage/          SQLite + CAS Artifact + Vector + Graph + Job
├── sandbox/          DockerBackend / TrustedSubprocess / Hardened
├── eval/             TaskEvaluator + Registry + Telemetry + Health + Metrics
├── agents/           Director / Coder / Critic / Meta / Router / LLMGateway
├── engine/           MCTS + Selection + Mutation + Crossover + Novelty + Memory + Island + Engine
├── meta/             PolicyGenome + Archive + Governance + PromptEvolver + HyperparamTuner + InfraAdapter + Audit
├── plugins/          BasePlugin + Quant + Geo
├── utils/            Embedding + TokenCounter + Hashing + Logging + ConfigSnapshot
├── config.py         OmniEvolveSettings (pydantic-settings)
└── cli.py            Typer CLI (run/status/best/export/policy/audit/recover/doctor)
```

### Fast Loop（单代候选进化）

```
1. Router.select          → 按角色分配模型
2. ParentSelector         → MCTS 引导选择父代
3. (可选) Crossover       → 多父代跨分支融合
4. Director               → 进化思想
5. NoveltyGate            → 多级新颖性门
6. Coder                  → 生成代码（带 Critic 重试）
7. ArtifactStore          → 保存 source / lineage / vector_index_job
8. TaskEvaluator          → build_plan
9. SandboxBackend         → execute
10. parse_result          → 分数 + 指标
11. 更新                  → best / island / MCTS / memory / router / budget
```

### Slow Loop（策略窗口评估与受控元进化）

```
每 health_window_gens 代：

TelemetryAggregator → 聚合 ROI/覆盖率/记忆/污染指标
       ↓
HealthPolicy.assess  → 生成 HealthOutput（OK/WARN/CRITICAL）
       ↓
MetaPlanner.propose  → 只生成允许的 MetaAction（L0/L1/L2 分级）
       ↓
Governance           → L0 自动；L1 必须 Replay/Canary；L2 禁止
       ↓
PolicyExperiment     → Champion vs Challenger，等预算比较
       ↓
Promote / Reject / Rollback
```

## 评估语义不可变边界

| 等级 | 规则 | 示例 |
|------|------|------|
| **L2** | 默认永久禁止自动修改 | Task semantics / correctness tests / hidden data / metric definition / score formula |
| **L1** | 允许提出 Challenger，必须 Replay/Canary | Timeout schedule / progressive stages / resource allocation / build cache |
| **L0** | 可自动调整并记录 | Log format / tracing / temp dir / cache eviction |

## 运行模式

| 安装档 | 内容 |
|--------|------|
| `omnievolve-core` | SQLite + Artifact Store + NumPy 检索 + TrustedSubprocess |
| `omnievolve-local` | core + zvec + 本地 Embedding + DockerBackend |
| `omnievolve-full` | local + 多模型路由 + Hardened/远程执行 + 高级 Policy Evolution |

## 测试

分层策略（Tier 1 CI → Tier 2 smoke → Tier 3 手动）：

```bash
make test              # Tier 1: 617 tests, FakeLLM, CI 默认
make test-cov          # Tier 1 + 覆盖率 (~82%)
make test-llm          # Tier 2: LLM 烟雾测试（需 API key）
make test-slow         # 慢速/集成测试（Docker, soak）
make test-all          # 全量（不含 LLM）

# 等效 pytest 命令
.venv/bin/python -m pytest -q -m "not slow and not llm"   # 617 tests
.venv/bin/python -m pytest --cov=omnievolve --cov-report=term
.venv/bin/python -m pytest tests/test_p0_quality_gates.py  # P0 架构门
.venv/bin/python -m pytest tests/test_soak.py -m slow      # 50代 soak
```

## 生产部署

### 最低要求

- Python 3.12+
- SQLite 3.35+（支持 FTS5）
- LLM API key（DeepSeek / OpenAI / Anthropic）

### 安全沙箱（推荐）

```bash
# Docker 安全沙箱（禁网、只读、降权、资源限制）
docker build -t omnievolve/sandbox:latest .
pip install -e ".[docker]"

# Monty Rust 沙箱（微秒级启动，无需 Docker daemon）
pip install -e ".[monty]"
```

### 熔断器配置

默认内置：5 次连续失败 → 断开 60s → 半开试探。

```python
from omnievolve.agents.circuit_breaker import CircuitBreaker, TokenBucketRateLimiter
from omnievolve.agents.llm_gateway import LLMGateway

gateway = LLMGateway(
    default_model="deepseek/deepseek-chat",
    circuit_breaker=CircuitBreaker(failure_threshold=5, reset_timeout_sec=60),
    rate_limiter=TokenBucketRateLimiter(capacity=10),  # 10 req/s
)
```

### 检查点恢复

每代自动持久化到 `experiment.checkpoint_data` 列。崩溃后：

```bash
omnievolve run ./code.py -e eval:MyEvaluator -c config.toml --resume <experiment_id>
```

### 可观测性（可选）

```bash
pip install opentelemetry-api opentelemetry-sdk opentelemetry-exporter-otlp
# 自动启用跨度跟踪和指标导出
```

详见 [PRODUCTION.md](./PRODUCTION.md)。

## 设计文档

完整设计文档位于 `docs/project-design/`，包括：
- `reference/OmniEvolve_v0.2_设计文档.md` — 主设计文档
- `01_项目总进度文档.md` — 进度跟踪
- `Sprint_Backlog/S1-S9` — 9 个 Sprint 的任务卡和验收条件

## 参考系统

- [OpenEvolve](https://github.com/codelion/openevolve) — 开源 AlphaEvolve 复现
- [ShinkaEvolve](https://github.com/Nevergoodenough/ShinkaEvolve) — 增量进化
- [DGM](https://github.com/codelion/dgm) — Darwin Gödel Machine
- [MLEvolve](https://github.com/codelion/mlevolve) — ML 任务进化
- [EvoX](https://github.com/EMI-Group/evox) — 进化计算框架

## 许可证

MIT
