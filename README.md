# OmniEvolve

**受控元进化框架 (Controlled Meta-Evolution Framework)** — LLM 驱动的代码自动进化优化

OmniEvolve 结合种群式代码搜索、分层记忆、两级新颖性评估和受控元进化（Slow Loop），支持任意领域的程序自动优化。Local-first 设计，零外部服务依赖即可运行。

- **双循环架构** — Fast Loop（单代候选进化 11 步）+ Slow Loop（策略窗口评估与受控元进化）
- **LineageUCB 搜索** — 按相对父代增益更新血缘信用，支持多父代交叉、岛屿局部选择与显式迁移
- **受控元进化** — L0/L1/L2 风险分级，Champion-Challenger 独立等预算 canary，评估语义永久不可变
- **默认安全** — Docker 沙箱（禁网、只读根、降权、资源限制），SHA-256 内容寻址 Artifact

## 目录

- [核心特性](#核心特性)
- [安装](#安装)
- [快速开始](#快速开始)
- [架构总览](#架构总览)
- [CLI 参考](#cli-参考)
- [配置参考](#配置参考)
- [运行模式](#运行模式)
- [测试](#测试)
- [生产部署](#生产部署)
- [文档索引](#文档索引)
- [参考系统](#参考系统)
- [许可证](#许可证)

## 核心特性

### 双循环进化架构

**Fast Loop**（单代候选进化，11 步）：

```
1.  ParentSelector         → 当前岛内用 LineageUCB 选择父代
2.  Router.select          → Director / Coder / Critic 分别路由模型
3.  (可选) Crossover       → 多父代跨分支融合
4.  Director               → 进化思想（"应该尝试什么方向"）
5.  IdeaNovelty            → Coder 前检查思路/机制重复
6.  Coder / Critic         → 生成并修复最终代码
7.  CandidateNovelty       → 对最终代码检查 exact / AST / embedding / epiplexity
8.  EvaluationService      → 静态校验、反作弊、progressive/hidden/repeated evaluation
9.  ArtifactStore          → 保存 source / lineage / vector_index_job
10. Commit                 → 串行提交评估和候选状态
11. 状态更新                → best / island / LineageUCB / memory / router / budget
```

**Slow Loop**（策略窗口评估与受控元进化，每 `health_window_gens` 代）：

普通运行默认 fail closed（`self_evolve_enabled = false`）；只有配置了真实 canary
executor 并显式启用时才运行。研究协议中的 `full` variant 会显式启用，
`no_slow_loop` 会显式关闭。

```
TelemetryAggregator  → 聚合 ROI/覆盖率/记忆/污染指标
       ↓
HealthPolicy.assess  → 生成 HealthOutput（OK / WARN / CRITICAL）
       ↓
MetaPlanner.propose  → 只生成允许的 MetaAction（L0/L1/L2 分级）
       ↓
Governance           → L0 自动；L1 必须 Replay/Canary；L2 禁止
       ↓
PolicyCanaryRunner   → 冻结 frontier、配对 seeds、独立等预算比较
       ↓
Promote / Reject / Rollback
```

### 搜索引擎

- **LineageUCB**：以 `score(child) - max(score(parents))` 回传血缘信用；`progressive_mcgs` 仅为弃用兼容别名
- **岛屿模型**：父代选择严格 island-local，只有带审计事件的周期迁移可引入外岛候选
- **多父代交叉**：segment / function-level / feature-merge
- **多级新颖性门**：防止重复探索，平衡探索与利用

### 记忆与检索

- **分层记忆 L0-L4**：分支级 → 实验级 → 任务族 → 领域 → 全局
- **向量 Outbox 最终一致性**：SQLite ↔ zvec/NumPy 自动同步
- **混合检索**：FTS5 BM25 + 向量语义召回 + scope filter
- **记忆引用/采用追踪**：评估记忆对决策的影响

### 安全与可信

- **评估语义不可变（L2）**：任务语义、正确性测试、隐藏数据、指标定义、分数公式永久禁止自动修改
- **内容寻址 Artifact Store**：SHA-256 去重、校验、复现
- **kill-9 恢复**：租约过期任务自动重新入队
- **配置快照与秘密遮蔽**

### 角色条件化路由

模型路由按角色分离奖励（Sliding-window UCB / Discounted UCB）：

| 角色 | 奖励组成 |
|------|----------|
| Director | thought_adoption + mechanism_novelty + frontier_contribution |
| Coder | patch_applied + compile_success + test_pass_rate + performance_gain |
| Critic | defect_recall − false_rejection_rate + evaluator_cost_saved |

### LLM-as-a-Verifier 概率验证层（实验性，默认关闭）

第一轮只做 observer-only 证据采集（PR 1-3）：通过硬正确性测试的候选产生
A/B 概率偏好证据（token logprob 期望、Bradley-Terry、G/K/C 聚合），写入独立
表与 ArtifactStore，**不修改 `passed` / `primary_score` / `search_score`**。
默认全关；`parent_pair` search credit、adaptive benchmark 与 island PPT 需 R1
离线校准门禁通过后才实现。详见 [集成计划](docs/llm_as_verifier_integration_plan.md)。

## 安装

要求 Python 3.12+。

```bash
# 核心（零外部服务依赖：SQLite + Artifact Store + NumPy 检索 + TrustedSubprocess）
pip install -e .

# 向量检索增强（HNSW ANN，百万级向量）
pip install -e ".[vector]"

# 本地 Embedding 模型（无需外部 API，自动 HF → hf-mirror → ModelScope 回退）
pip install -e ".[local-embed]"

# Docker 沙箱（禁网、只读、降权）
pip install -e ".[docker]"

# Monty 沙箱（Rust 实现，微秒级启动）
pip install -e ".[monty]"

# 可视化 / 超参调优 / 性能分析
pip install -e ".[viz]"
pip install -e ".[tuning]"
pip install -e ".[profile]"

# 全量
pip install -e ".[all]"
```

可用的安装档（extras）：`vector`、`local-embed`、`docker`、`monty`、`viz`、`tuning`、`profile`、`all`。

LLM API key 通过环境变量或 `.env` 文件配置：

```bash
export DEEPSEEK_API_KEY="sk-..."    # 或 OPENAI_API_KEY / ANTHROPIC_API_KEY
```

## 快速开始

### 1. 创建配置

```bash
cp configs/omnievolve.toml.example omnievolve.toml
# 编辑模型名、沙箱后端、API key 路径等
```

### 2. 实现评估器

评估器是 OmniEvolve 与具体任务之间的桥梁，只需实现三个方法：

```python
# my_evaluator.py
from omnievolve.eval.task_evaluator import (
    CandidateArtifact,
    EvalOutput,
    EvaluationContext,
    EvaluationPlan,
    CommandSpec,
    SandboxExecutionResult,
)

class MyEvaluator:
    """任务评估器：构建声明式评估计划 + 解析沙箱结果。"""

    version_id = "my-evaluator@1.0.0"

    def build_plan(self, candidate: CandidateArtifact, context: EvaluationContext):
        return EvaluationPlan(
            commands=[CommandSpec(argv=["python", "-m", "pytest", "-v"])],
        )

    def parse_result(self, result: SandboxExecutionResult, context: EvaluationContext):
        ok = result.return_codes and result.return_codes[0] == 0
        return EvalOutput(
            score=1.0 if ok else 0.0,
            metrics={},
            passed=ok,
        )

    def get_baseline(self) -> float:
        return 0.5
```

详见 [评估器开发指南](docs/evaluator_guide.md)。

### 3. 运行进化

```bash
# 本地 trusted 模式（开发/测试，无需 Docker）
omnievolve run ./initial_code.py \
    --evaluator my_evaluator:MyEvaluator \
    --config omnievolve.toml \
    --gens 30 \
    --trusted

# Docker 安全模式（生产推荐，需 Docker daemon）
# 在 omnievolve.toml 中设置 sandbox.backend = "docker"
omnievolve run ./initial_code.py \
    --evaluator my_evaluator:MyEvaluator \
    --config omnievolve.toml \
    --gens 30

# Monty 安全模式（Rust 沙箱，微秒级启动）
# 在 omnievolve.toml 中设置 sandbox.backend = "monty"
omnievolve run ./initial_code.py \
    --evaluator my_evaluator:MyEvaluator \
    --config omnievolve.toml \
    --gens 30

# 断点续跑（崩溃恢复）
omnievolve run ./initial_code.py \
    --evaluator my_evaluator:MyEvaluator \
    --config omnievolve.toml \
    --resume exp_a3f8c2

# 仅运行 Fast Loop（关闭 Slow Loop 受控策略进化）
omnievolve run ./initial_code.py \
    --evaluator my_evaluator:MyEvaluator \
    --config omnievolve.toml \
    --no-self-evolve
```

### 4. 查看结果

```bash
omnievolve status exp_a3f8c2       # 进度、Champion Policy、Top 候选、健康状态
omnievolve best exp_a3f8c2 --code  # 最优候选完整源码
omnievolve policy exp_a3f8c2       # Champion/Challenger 策略谱系
omnievolve audit exp_a3f8c2        # 端到端审计报告（哈希、版本、缺失索引）
omnievolve export exp_a3f8c2       # 导出进化图（GraphML / JSON）
omnievolve recover exp_a3f8c2      # 扫描租约/Outbox/孤立 Artifact
omnievolve doctor                  # 环境检测
```

完整示例参见 `examples/` 目录（`python_optimization`、`circle_packing`、`heilbronn`、`matmul`）。

## 架构总览

交互式 HTML 架构图位于 `docs/architecture/`（浏览器打开即可，支持暗/亮主题、语义聚焦、PNG/SVG 导出）：

- [系统总览](docs/architecture/system-overview.html) — 全局模块关系：Engine / Agents / Storage / Sandbox / Meta 的数据流和控制流
- [Fast Loop](docs/architecture/fast-loop.html) — 单候选 11 步进化流水线
- [Slow Loop](docs/architecture/slow-loop.html) — 策略窗口评估与受控元进化
- [存储架构](docs/architecture/storage.html) — 持久化层：SQLite + CAS Artifact + Vector (HNSW) + Graph + Git Code Store

### 模块结构

```
src/omnievolve/
├── engine/     进化引擎：EvolutionEngine + FastLoopStep + MCTS + Selection + Mutation + Crossover + Novelty + Memory + Island + SlowLoop + AsyncPipelineEngine
├── agents/     LLM Agent：Director / Coder / Critic / LLMGateway(熔断器+限流) / ModelRouter / ContextBuilder
├── eval/       评估：TaskEvaluator(Protocol) + EvaluatorRegistry + EvaluationRun + Telemetry + HealthPolicy + Metrics + PlanValidator
├── meta/       元进化：PolicyGenome + PolicyArchive + Governance(L0/L1/L2) + BayesianTuner(GP+EI) + InfraAdapter + AuditReport + PromptEvolver
├── sandbox/    沙箱：TrustedSubprocessBackend / DockerBackend / MontyBackend / HardenedBackend
├── storage/    存储：SQLite DB + ArtifactStore(SHA-256 CAS) + GitCodeStore + GraphStore + VectorStore + HybridRetriever + ZvecBackend(HNSW) + JobStore + UnitOfWork
├── plugins/    插件：BasePlugin + QuantPlugin + GeoPlugin + PluginDiscovery
├── utils/      工具：Embedding(SentenceTransformer+LiteLLM+Fake) + TokenCounter + SeedManager + ConfigSnapshot + Hashing + Profiling
├── cli.py      Typer CLI（run/status/best/export/policy/audit/recover/migrate/doctor）
└── config.py   OmniEvolveSettings（pydantic-settings，从 omnievolve.toml 加载）
```

### 数据流

```
初始代码
   ↓
EvolutionEngine.run()
   ↓
┌─────────────────────── Fast Loop（每代重复）──────────────────────────┐
│  ParentSelector(LineageUCB) → [Crossover] → Director → IdeaNovelty     │
│  → Coder/Critic → CandidateNovelty → EvaluationService → ArtifactStore │
│  → Commit → 状态更新(LineageUCB/Island/Memory/Router/Budget)            │
└──────────────────────────────────────────────────────────────────────┘
   ↓ 每 health_window_gens 代
┌─────────────────────── Slow Loop ───────────────────────────────────┐
│  Telemetry → HealthPolicy → MetaPlanner → Governance(L0/L1/L2)       │
│  → PolicyCanaryRunner（独立等预算）→ Promote / Hold / Reject            │
└──────────────────────────────────────────────────────────────────────┘
   ↓
最优候选 + Champion Policy + 完整审计链
```

### 评估语义不可变边界

| 等级 | 规则 | 示例 |
|------|------|------|
| **L2** | 默认永久禁止自动修改 | Task semantics / correctness tests / hidden data / metric definition / score formula |
| **L1** | 允许提出 Challenger，必须 Replay/Canary | Timeout schedule / progressive stages / resource allocation / build cache |
| **L0** | 可自动调整并记录 | Log format / tracing / temp dir / cache eviction |

## CLI 参考

OmniEvolve 提供 9 个 CLI 命令：

### `run` — 启动候选进化

```bash
omnievolve run <task> --evaluator <module:Class> [选项]
```

| 选项 | 说明 |
|------|------|
| `--config, -c` | 配置文件路径（默认 `omnievolve.toml`） |
| `--evaluator, -e` | 评估器路径，格式 `module:Class`（必填） |
| `--gens, -g` | 最大代数（覆盖配置） |
| `--resume` | 恢复实验 ID（断点续跑） |
| `--trusted` | 启用非隔离 subprocess 模式（开发用） |
| `--no-self-evolve` | 关闭 Slow Loop，仅运行 Fast Loop |

### `status` — 查看进化进度

```bash
omnievolve status <experiment_id>
```

输出实验状态、代数/候选数、Top 候选分数、Champion Policy 谱系。

### `best` — 输出最优候选

```bash
omnievolve best <experiment_id> [--code]
```

`--code` 打印最优候选的完整源码。

### `export` — 导出进化图

```bash
omnievolve export <experiment_id> [--format graphml|json] [--output <path>]
```

导出血缘图（含 reference edges），支持 GraphML 和 JSON 格式。

### `policy` — 查看策略谱系

```bash
omnievolve policy <experiment_id>
```

显示 Champion / Challenger 策略版本、状态和风险等级。

### `audit` — 端到端审计报告

```bash
omnievolve audit <experiment_id> [--full] [--output report.json]
```

检查 Artifact 哈希完整性、评估器版本、缺失向量索引、过期租约。

### `recover` — 故障恢复

```bash
omnievolve recover <experiment_id> [--dry-run|--apply]
```

扫描租约过期任务、未完成 Outbox 和孤立 Artifact，可修复或仅扫描。

### `migrate` — 数据库迁移

```bash
omnievolve migrate [--dry-run]
```

执行数据库 schema 迁移（自动版本检测）。

### `doctor` — 环境检测

```bash
omnievolve doctor
```

### `research` — 多任务、多种子消融基准

```bash
# 先生成固定 3 tasks × 5 variants × 3 paired seeds = 45 runs pilot
omnievolve research plan-pilot \
  --calibration .omnievolve/research/calibration.json \
  --output .omnievolve/research/pilot-matrix.json

# 门禁要求显式确认 deterministic replay；价格未知时须预先排除成本指标
omnievolve research analyze \
  --results .omnievolve/research/results.jsonl \
  --deterministic-replay-passed
```

完整协议见 [docs/research_benchmark.md](docs/research_benchmark.md)。

检查 Python 版本、依赖包、沙箱后端可用性、SQLite FTS5 支持。

## 配置参考

OmniEvolve 通过 `omnievolve.toml` 配置。完整示例见 `configs/omnievolve.toml.example`。

优先级：**显式进程环境 > `.local.env` > `.env` > 配置文件 > 默认值**。环境变量前缀 `OMNIEVOLVE_`，嵌套用 `__` 分隔（如 `OMNIEVOLVE_EVOLUTION__MAX_GENERATIONS`）。本地密钥应放在 gitignored `.local.env`，不要提交真实凭据。

### 主要配置项

```toml
[evolution]
max_generations = 10          # 最大进化代数
population_size = 8           # 每代种群大小
island_count = 4              # 岛屿数量
novelty_threshold = 0.92      # 新颖性阈值（0-1）
mutation_rate = 0.3           # 变异率
crossover_rate = 0.15         # 交叉率
max_stagnation_gens = 5       # 最大停滞代数（触发岛屿重置）
token_budget = 2_000_000      # 总 token 预算（耗尽自动停止）
compute_budget_sec = 0         # 0 表示不限时；正数才是硬上限
health_window_gens = 3        # Slow Loop 评估窗口（代）
self_evolve_enabled = false   # 默认 fail closed；真实 canary 就绪后才显式启用
async_pipeline_enabled = false # 异步流水线引擎（实验性）
qd_archive_enabled = false      # 最小行为单元档案（独立消融，默认关闭）
qd_parent_probability = 0.15    # 从当前岛 QD 档案采样父代的概率
operator_portfolio_enabled = false # UCB/Thompson 算子调度（独立消融）
operator_portfolio_algorithm = "ucb" # ucb / thompson

[selection]
parent_selector = "lineage_ucb"
tournament_size = 3
island_migration_interval = 5

[models]
heavy = ["gpt-4o"]            # 重型模型（Director/Coder）
light = ["gpt-4o-mini"]       # 轻型模型（Critic）
max_tokens = 16384            # 默认最大输出 token（可被 agent 覆盖）

[models.routing]
algorithm = "sliding_window_ucb"  # sliding_window_ucb / discounted_ucb / thompson
window_size = 50
ucb_c = 1.414

[embedding.code]
provider = "local"            # local / openai / voyage / fake
model = "Qwen/Qwen3-Embedding-0.6B"
dimension = 1024

[novelty]
embedding_gate = true
ast_gate = true
behavior_gate = false
llm_judge_on_borderline = true

[sandbox]
backend = "docker"             # 安全默认；trusted_subprocess 仅用于显式本地开发
timeout_sec = 30
mem_limit_mb = 512

[storage]
db_path = ".omnievolve/omnievolve.db"
artifact_dir = ".omnievolve/artifacts"
code_backend = "cas"          # cas（默认）/ git（可选文本血缘后端）

[meta_evolution]
enabled = true
prompt_mutation_rate = 0.2
auto_apply_l0 = true          # L0 动作自动应用
require_replay_for_l1 = true  # L1 动作需 Replay 验证
allow_l2_actions = false      # L2 动作默认禁止

[evaluation_governance]
immutable_task_semantics = true
immutable_correctness_tests = true
immutable_score_formula = true
```

完整配置项参见 `src/omnievolve/config.py`。

## 运行模式

| 模式 | 命令 | 安全性 | 适用场景 |
|------|------|--------|----------|
| **Trusted Subprocess** | `--trusted` 或 `sandbox.backend = "trusted_subprocess"` | 无隔离（宿主机权限） | 本地开发、可信代码、快速迭代 |
| **Docker** | `sandbox.backend = "docker"` | 禁网、只读根、降权、资源限制 | 生产部署、不可信代码 |
| **Monty** | `sandbox.backend = "monty"` | Rust 沙箱隔离，微秒级启动 | 高频评估、无 Docker 环境 |
| **Hardened** | `HardenedBackend` | gVisor / nsjail / Firecracker | 强隔离需求 |

Docker 安全沙箱构建：

```bash
docker build -t omnievolve/sandbox:latest .
```

详见 [Docker 安全基线](docs/docker_security_baseline.md)。

## 测试

采用分层测试策略（Tier 1 CI → Tier 2 smoke → Tier 3 手动），避免每次测试都消耗 API 配额：

```bash
make test              # Tier 1: 快速单元测试（FakeLLM，CI 默认，~36s）
make test-cov          # Tier 1 + 覆盖率
make test-llm          # Tier 2: LLM 烟雾测试（2-3 代真实进化，需 API key）
make test-slow         # 慢速/集成测试（Docker、soak 50 代）
make test-all          # 全量（不含 LLM）

# 等效 pytest 命令
.venv/bin/python -m pytest -q -m "not slow and not llm"   # Tier 1
.venv/bin/python -m pytest --cov=omnievolve --cov-report=term
.venv/bin/python -m pytest tests/test_p0_quality_gates.py  # P0 架构门
.venv/bin/python -m pytest tests/test_soak.py -m slow      # 50 代 soak 稳定性
```

代码质量：

```bash
make lint          # ruff check
make type-check    # mypy
```

详见 [分层 LLM 测试策略](docs/release_notes_v0.2.md)。

## 生产部署

### 最低要求

- Python 3.12+
- SQLite 3.35+（支持 FTS5）
- LLM API key（DeepSeek / OpenAI / Anthropic）

### 熔断器与限流

默认内置熔断器（5 次连续失败 → 断开 60s → 半开试探）和令牌桶限流器：

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

每代自动持久化到 `experiment.checkpoint_data`。崩溃后断点续跑：

```bash
omnievolve run ./code.py -e eval:MyEvaluator -c config.toml --resume <experiment_id>
```

### 可观测性（可选）

```bash
pip install opentelemetry-api opentelemetry-sdk opentelemetry-exporter-otlp
# 自动启用跨度跟踪和指标导出
```

完整生产运维指南（部署清单、监控指标、故障恢复、性能基线）详见 [PRODUCTION.md](PRODUCTION.md)。

## 文档索引

| 文档 | 内容 |
|------|------|
| [架构图](docs/architecture/README.md) | 交互式 HTML 架构图（系统总览 / Fast Loop / Slow Loop / 存储架构） |
| [PRODUCTION.md](PRODUCTION.md) | 生产部署指南、监控指标、故障恢复 |
| [存储 ADR](docs/storage_adr.md) | 存储架构决策（SQLite WAL、SHA-256 CAS、Git 后端） |
| [评估器开发指南](docs/evaluator_guide.md) | TaskEvaluator Protocol、评估模式、注册方式 |
| [Agent 开发指南](docs/prompt_agent_guide.md) | Agent 架构、Prompt 版本化、结构化输出修复 |
| [健康指标](docs/health_metrics.md) | ROI/覆盖率/记忆有效性公式与限制 |
| [向量配置](docs/vector_configuration.md) | 向量后端（NumPy/zvec）、Embedding、索引生命周期 |
| [Docker 安全基线](docs/docker_security_baseline.md) | Docker 安全策略与残余风险 |
| [LLM-as-a-Verifier 集成计划](docs/llm_as_verifier_integration_plan.md) | 概率验证层设计、R1-R4 研究协议、PR 边界与实施记录 |
| [v0.2 发布说明](docs/release_notes_v0.2.md) | 版本特性、已知限制、参考系统 |

## 参考系统

OmniEvolve 吸收了以下系统的设计理念：

- [AlphaEvolve](https://github.com/codelion/openevolve) (Google DeepMind) — SEARCH/REPLACE diff、EVOLVE-BLOCK、Rich Prompt、PromptEvolver
- [ShinkaEvolve](https://github.com/Nevergoodenough/ShinkaEvolve) (Sakana AI) — Power law/weighted 采样、Meta-scratchpad、Bandit relative reward
- [MLEvolve](https://github.com/codelion/mlevolve) — Reference edges、Progressive exploration schedule
- [OpenEvolve](https://github.com/codelion/openevolve) — 开源 AlphaEvolve 复现
- [DGM](https://github.com/codelion/dgm) — Darwin Gödel Machine，开放式自改进
- [EvoX](https://github.com/EMI-Group/evox) — 进化计算框架

## 许可证

MIT
