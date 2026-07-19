# OmniEvolve 设计文档 / 技术方案 / 接口定义

> **版本**: v0.2-draft  
> **日期**: 2026-07-19  
> **定位**: Local-first、evaluator-agnostic、auditable 的双循环自进化框架；无强制数据库服务，单机可运行，并通过受控、可验证、可回滚的元进化持续优化候选解与搜索策略。
>
> **修订说明**：本版以 v0.1 为底稿做增量修改，保留原有十四章结构、模块命名和主要工作流；重点修正安全沙箱、评估边界、图数据模型、存储一致性和元进化治理，不另起一套架构。

---

## 一、设计哲学与约束

| 原则 | 落地方式 |
|------|---------|
| Local-first / 低运维 | 所有核心状态默认存放于本地 `.omnievolve/` 目录；不强制部署 Neo4j、Milvus、PostgreSQL 等外部服务，也不要求常驻 daemon |
| 单体集成 | 一个 Python 包内统一编排图、向量、关系数据、Artifact 和执行任务；高级后端通过 Adapter 可选替换 |
| 可断点续跑 | 已提交事务、候选 Artifact、任务租约和评估结果持久化；进程被终止后可恢复已完成工作，并重新认领未完成或租约过期任务 |
| 插件化评估 | 任务评估器由用户实现，但只能声明评估计划和解析结果，不能绕过 Sandbox 直接执行候选代码 |
| 双轨解耦 | 轨道 A 评估候选解质量；轨道 B 评估某个 `SearchPolicyVersion` 在一段窗口内的搜索健康度，二者不混成同一个节点分数 |
| 评估主权 | Task semantics、正确性测试、隐藏数据、评分公式和聚合规则属于不可变评估核心，Meta-Agent 无权修改 |
| 受控元进化 | Search Policy、Prompt、路由和搜索超参数可版本化进化；变更必须经过风险分级、Replay/Canary、Champion-Challenger 比较和可回滚发布 |
| 完整可审计 | 每个候选、父代关系、模型调用、Prompt、策略、执行环境、评估器和随机种子均记录版本与来源 |
| 成本可控 | 内置 token、API 费用、沙箱算力和墙钟时间计量；采用角色条件化的非平稳 Bandit 路由，而非固定“前重后轻”策略 |
| 安全默认 | Docker 隔离为默认执行后端；`subprocess + rlimit` 仅作为用户显式开启的可信代码模式，不宣称为安全沙箱 |

### 1.1 双循环设计哲学

v0.1 的四层模块划分继续保留，但系统运行逻辑明确为两个时间尺度不同的闭环：

```text
Fast Loop：Candidate Evolution
Parent Selection
→ Thought Proposal
→ Novelty Gate
→ Code Realization
→ Static Review
→ Sandboxed Evaluation
→ Candidate Archive

Slow Loop：Policy Evolution
Telemetry Aggregation
→ Process Evaluation
→ Policy Challenger Generation
→ Replay / Canary Evaluation
→ Champion Promotion or Rollback
```

- **Fast Loop** 解决“候选代码如何变好”；
- **Slow Loop** 解决“生成和筛选候选代码的规则如何变好”；
- Slow Loop 不直接篡改 Fast Loop 的任务目标，而是调整搜索策略、上下文、模型路由和评估基础设施的非语义参数。

---

## 二、技术选型

为了保持 v0.1 的嵌入式单体方向，同时补齐安全性、可复现性和一致性，技术选型调整如下：

| 职责 | 选型 | 理由 |
|------|------|------|
| 关系存储 / 图结构 / 元数据 | **SQLite**（WAL 模式） | 嵌入式、ACID、单文件；持久化实验、图血缘、策略版本、任务租约和评估记录 |
| Artifact 存储 | **本地内容寻址文件系统（CAS）** | 代码、Diff、Manifest、日志和评估输出按 SHA-256 保存，避免把大段代码和二进制结果塞入 SQLite |
| 向量存储 / 新颖性去重 / RAG | **zvec Adapter**；核心模式可退化为 NumPy 精确检索 | zvec 提供嵌入式 ANN；业务层不绑定具体 API；通过 SQLite Outbox 保证索引最终一致性 |
| 内存图算法（MCTS/融合） | **NetworkX** | 从 SQLite 加载限定子图进行 MCTS、岛屿迁移和跨分支融合，结果回写 |
| 代码嵌入 | `voyage-code-3`（API）或用户配置的本地代码向量模型 | 通过 `EmbeddingProfile` 记录 provider、model、revision、dimension 和归一化方式，不写死模糊模型名 |
| 思想嵌入 | `bge-m3`（本地）或 `text-embedding-3-small`（API） | 文本语义；与代码嵌入使用独立 Profile 和独立索引 |
| 词法检索 | SQLite **FTS5** | 与向量召回进行混合检索，支持作用域过滤和可解释关键词命中 |
| LLM 调用 | `litellm` 统一网关 | 一套代码连接 API 与本地模型；所有调用记录模型、Prompt 版本、token、费用和延迟 |
| 默认安全执行 | **DockerBackend** | 禁网、只读根文件系统、降权、资源限制和独立工作区；作为默认候选执行后端 |
| 可信执行 | `TrustedSubprocessBackend` | 仅供用户明确确认的可信代码或本地开发调试；不作为安全边界 |
| 强隔离执行 | `HardenedBackend` Adapter | 可接 gVisor、nsjail、Firecracker、E2B、Modal 等实现 |
| 配置 | `pydantic-settings` + `omnievolve.toml` | 类型安全、分层覆盖、可审计快照 |
| CLI | `typer` | 命令行入口 |
| 包管理 | `uv` / `pip` | 分发；按 core/local/full 分档安装 |

**运行模式而非“零依赖”承诺**：

```text
omnievolve-core
    SQLite + 本地 Artifact Store + NumPy 检索 + Trusted Mode

omnievolve-local
    core + zvec + 本地 Embedding + DockerBackend

omnievolve-full
    local + 多模型路由 + Hardened/远程执行 + 高级 Policy Evolution
```

因此 v0.2 的准确表述是：**无强制外部数据库服务、无强制常驻进程、Local-first、单机可运行**。远程模型、本地大模型、Docker 或云沙箱按任务和安全级别选配。

---

## 三、系统架构（四层 → 单体落地）

v0.1 的目录结构不推翻，只在原模块内补充 Artifact、Telemetry、Policy 和执行治理：

```text
omnievolve/
├── __init__.py
├── cli.py                    # typer 入口
├── config.py                 # pydantic-settings 配置
│
├── storage/                  # ── 存储层（全部嵌入式）──
│   ├── db.py                 # SQLite 连接管理、WAL、事务
│   ├── schema.sql            # DDL
│   ├── artifact_store.py     # 内容寻址 Artifact Store（SHA-256）
│   ├── graph_store.py        # Candidate 血缘 / 引用边 CRUD → NetworkX
│   ├── vector_backend.py     # VectorBackend Protocol
│   ├── zvec_backend.py       # zvec Adapter
│   ├── vector_indexer.py     # Outbox 消费与幂等索引
│   ├── job_store.py          # job lease / heartbeat / retry / recovery
│   └── migrations/           # 版本号迁移
│
├── agents/                   # ── 智能体编排层 ──
│   ├── base.py               # Agent 基类 / Protocol
│   ├── director.py           # 思想进化
│   ├── coder.py              # Thought → Code Diff
│   ├── critic.py             # 静态审查
│   ├── meta.py               # MetaPlanner：提出受控策略变更
│   └── router.py             # 角色条件化 Sliding-window UCB / Thompson
│
├── engine/                   # ── 候选进化引擎层（Fast Loop）──
│   ├── mcts.py               # 渐进式 MCGS / 可选 MCTS
│   ├── selection.py          # 父代、岛屿、Pareto/锦标赛选择
│   ├── mutation.py           # 变异算子（Diff 生成策略）
│   ├── crossover.py          # 多父代跨分支融合
│   ├── novelty.py            # Embedding + AST + 行为签名多级新颖性门
│   ├── memory.py             # 分层全局记忆（L0~L4）
│   └── scheduler.py          # 主循环、代际管理、任务租约、恢复
│
├── eval/                     # ── 双轨评估层 ──
│   ├── task_evaluator.py     # 轨道A：构造 EvaluationPlan + 解析结果
│   ├── evaluator_registry.py # 评估器版本、数据集哈希、不可变语义
│   ├── self_evaluator.py     # 轨道B Facade
│   ├── telemetry.py          # TelemetryAggregator：客观数据聚合
│   ├── health_policy.py      # HealthPolicy：规则/统计判定
│   ├── metrics.py            # ROI、覆盖率、记忆有效性、污染度
│   └── environment.py        # ExecutionEnvironmentVersion 管理
│
├── sandbox/                  # ── 执行隔离层 ──
│   ├── base.py               # SandboxBackend Protocol
│   ├── docker_backend.py     # 默认后端
│   ├── subprocess_backend.py # 可信模式
│   └── hardened_backend.py   # gVisor / nsjail / Firecracker / E2B Adapter
│
├── meta/                     # ── 策略进化层（Slow Loop）──
│   ├── policy_genome.py      # SearchPolicyGenome
│   ├── policy_archive.py     # Champion / Challenger / 回滚
│   ├── prompt_evolver.py     # Prompt 基因变异
│   ├── hyperparam_tuner.py   # 搜索参数调优；首版可用规则/Bandit
│   ├── replay_evaluator.py   # 等预算离线 Replay / Canary
│   ├── infra_adapter.py      # 非语义性评估基础设施适配
│   └── governance.py         # L0/L1/L2 风险分级和发布门禁
│
├── plugins/                  # ── 领域插件（热插拔）──
│   ├── base.py               # Plugin Protocol
│   ├── geo/
│   └── quant/
│
└── utils/
    ├── embedding.py          # EmbeddingProfile + 统一接口
    ├── token_counter.py      # Token / API / compute 计量
    ├── hashing.py            # 内容哈希与 Manifest
    └── logging.py            # 结构化日志 / provenance
```

**数据目录（运行时生成）**：

```text
.omnievolve/
├── omnievolve.db                 # SQLite：图、版本、任务、日志、Outbox
├── artifacts/
│   └── sha256/ab/cd/<hash>       # 代码、Diff、Manifest、stdout/stderr、报告
├── vectors/
│   ├── code/<profile_id>/        # 代码向量索引
│   └── thought/<profile_id>/     # 思想向量索引
├── sandbox/                      # 隔离执行的临时工作目录
├── exports/                      # GraphML、报告和最佳候选导出
├── policies/                     # 可读的策略与 Prompt 快照
└── omnievolve.toml               # 运行时配置（可覆盖）
```

### 3.1 五类一等实体

系统所有核心操作围绕以下五类实体建立，不再把所有信息混入单一 `evo_node`：

```text
CandidateArtifact
TaskEvaluatorVersion
ExecutionEnvironmentVersion
SearchPolicyVersion
EvaluationRun
```

扩展实体包括：

```text
ThoughtRecord
CandidateLineage
MemoryRecord
PromptVersion
EmbeddingProfile
MetaEvaluationWindow
PolicyExperiment
```

---

## 四、数据模型

### 4.1 SQLite Schema（`schema.sql`）

v0.2 继续使用 SQLite，但将 v0.1 的 `evo_node` 拆分为 Candidate、Artifact、Lineage 和 EvaluationRun；`health_score` 不再属于单个候选节点，而属于某个策略版本的评估窗口。

```sql
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;
PRAGMA busy_timeout = 5000;

-- ═══════════════════════════════════════════
-- 实验与任务作用域
-- ═══════════════════════════════════════════
CREATE TABLE IF NOT EXISTS experiment (
    id                  TEXT PRIMARY KEY,
    task_id             TEXT NOT NULL,
    task_name           TEXT NOT NULL,
    domain_id           TEXT,
    status              TEXT NOT NULL DEFAULT 'created',
    config_snapshot     TEXT NOT NULL,              -- JSON
    baseline_candidate_id TEXT,
    champion_policy_id  TEXT,
    started_at          TEXT DEFAULT (datetime('now')),
    finished_at         TEXT,
    total_tokens        INTEGER DEFAULT 0,
    total_cost_usd      REAL DEFAULT 0,
    total_compute_sec   REAL DEFAULT 0
);

-- ═══════════════════════════════════════════
-- 内容寻址 Artifact 元数据
-- ═══════════════════════════════════════════
CREATE TABLE IF NOT EXISTS artifact (
    hash                TEXT PRIMARY KEY,           -- sha256
    artifact_type       TEXT NOT NULL,              -- source/diff/manifest/log/report/binary
    byte_size           INTEGER NOT NULL,
    media_type          TEXT,
    relative_path       TEXT NOT NULL,
    base_artifact_hash  TEXT REFERENCES artifact(hash),
    created_at          TEXT DEFAULT (datetime('now')),
    meta                TEXT                        -- JSON
);

-- ═══════════════════════════════════════════
-- 思想记录
-- ═══════════════════════════════════════════
CREATE TABLE IF NOT EXISTS thought_record (
    id                  TEXT PRIMARY KEY,
    experiment_id       TEXT NOT NULL REFERENCES experiment(id),
    task_id             TEXT NOT NULL,
    domain_id           TEXT,
    content             TEXT NOT NULL,
    rationale           TEXT,
    risk_notes          TEXT,
    confidence          REAL,
    prompt_version_id   TEXT,
    model_call_id       TEXT,
    created_at          TEXT DEFAULT (datetime('now'))
);

-- ═══════════════════════════════════════════
-- Candidate：只描述候选身份和搜索状态
-- ═══════════════════════════════════════════
CREATE TABLE IF NOT EXISTS candidate (
    id                  TEXT PRIMARY KEY,
    experiment_id       TEXT NOT NULL REFERENCES experiment(id),
    task_id             TEXT NOT NULL,
    generation          INTEGER NOT NULL,
    island_id           TEXT,
    thought_id          TEXT REFERENCES thought_record(id),
    artifact_hash       TEXT NOT NULL REFERENCES artifact(hash),
    diff_artifact_hash  TEXT REFERENCES artifact(hash),
    manifest_hash       TEXT REFERENCES artifact(hash),
    search_policy_id    TEXT NOT NULL,
    status              TEXT NOT NULL DEFAULT 'pending',
    novelty_score       REAL,
    created_at          TEXT DEFAULT (datetime('now')),
    meta                TEXT                        -- JSON
);

CREATE INDEX IF NOT EXISTS idx_candidate_exp_gen
    ON candidate(experiment_id, generation);
CREATE INDEX IF NOT EXISTS idx_candidate_policy
    ON candidate(search_policy_id);
CREATE INDEX IF NOT EXISTS idx_candidate_status
    ON candidate(status);

-- ═══════════════════════════════════════════
-- 多父代血缘：唯一的父代事实来源
-- ═══════════════════════════════════════════
CREATE TABLE IF NOT EXISTS candidate_lineage (
    child_id            TEXT NOT NULL REFERENCES candidate(id),
    parent_id           TEXT NOT NULL REFERENCES candidate(id),
    relation_type       TEXT NOT NULL,              -- mutate/crossover/repair/import
    parent_order        INTEGER DEFAULT 0,
    op_detail           TEXT,                       -- JSON
    created_at          TEXT DEFAULT (datetime('now')),
    PRIMARY KEY(child_id, parent_id, relation_type)
);

CREATE INDEX IF NOT EXISTS idx_lineage_parent
    ON candidate_lineage(parent_id);

-- 非父代引用边：跨分支借鉴、RAG 引用、Critic 修复来源
CREATE TABLE IF NOT EXISTS candidate_reference_edge (
    src_candidate_id    TEXT NOT NULL REFERENCES candidate(id),
    dst_candidate_id    TEXT NOT NULL REFERENCES candidate(id),
    reference_type      TEXT NOT NULL,              -- memory/reference/crossover_hint/critic_fix
    detail              TEXT,
    created_at          TEXT DEFAULT (datetime('now')),
    PRIMARY KEY(src_candidate_id, dst_candidate_id, reference_type)
);

-- MCTS / MCGS 的搜索统计与 Candidate 身份分离
CREATE TABLE IF NOT EXISTS candidate_search_state (
    candidate_id        TEXT PRIMARY KEY REFERENCES candidate(id),
    visit_count         INTEGER DEFAULT 0,
    value_sum           REAL DEFAULT 0,
    prior               REAL DEFAULT 0,
    virtual_loss        REAL DEFAULT 0,
    selection_count     INTEGER DEFAULT 0,
    offspring_count     INTEGER DEFAULT 0,
    frontier_status     TEXT DEFAULT 'open',        -- open/closed/pruned/elite
    updated_at          TEXT DEFAULT (datetime('now'))
);

-- ═══════════════════════════════════════════
-- 轨道 A：任务评估器和执行环境版本
-- ═══════════════════════════════════════════
CREATE TABLE IF NOT EXISTS task_evaluator_version (
    id                  TEXT PRIMARY KEY,
    name                TEXT NOT NULL,
    semantic_version    TEXT NOT NULL,
    implementation_hash TEXT NOT NULL,
    dataset_hash        TEXT,
    task_semantics_hash TEXT NOT NULL,
    score_schema        TEXT NOT NULL,              -- JSON
    immutable_core      INTEGER NOT NULL DEFAULT 1,
    created_at          TEXT DEFAULT (datetime('now')),
    UNIQUE(name, semantic_version, implementation_hash)
);

CREATE TABLE IF NOT EXISTS execution_environment_version (
    id                  TEXT PRIMARY KEY,
    backend             TEXT NOT NULL,              -- docker/trusted_subprocess/hardened
    image_digest        TEXT,
    compiler_digest     TEXT,
    dependency_lock_hash TEXT,
    cpu_profile         TEXT,
    resource_policy     TEXT NOT NULL,              -- JSON
    network_policy      TEXT NOT NULL,
    created_at          TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS evaluation_run (
    id                  TEXT PRIMARY KEY,
    experiment_id       TEXT NOT NULL REFERENCES experiment(id),
    candidate_id        TEXT NOT NULL REFERENCES candidate(id),
    evaluator_version_id TEXT NOT NULL REFERENCES task_evaluator_version(id),
    environment_version_id TEXT NOT NULL REFERENCES execution_environment_version(id),
    seed                INTEGER,
    split_name          TEXT DEFAULT 'default',
    attempt             INTEGER DEFAULT 1,
    status              TEXT NOT NULL DEFAULT 'queued',
    passed              INTEGER,
    primary_score       REAL,
    metrics             TEXT,                       -- JSON
    execution_time_ms   REAL,
    memory_peak_kb      INTEGER,
    cpu_time_ms         REAL,
    stdout_hash         TEXT REFERENCES artifact(hash),
    stderr_hash         TEXT REFERENCES artifact(hash),
    result_hash         TEXT REFERENCES artifact(hash),
    started_at          TEXT,
    finished_at         TEXT,
    UNIQUE(candidate_id, evaluator_version_id, environment_version_id, seed, split_name, attempt)
);

CREATE INDEX IF NOT EXISTS idx_eval_candidate
    ON evaluation_run(candidate_id);
CREATE INDEX IF NOT EXISTS idx_eval_scope
    ON evaluation_run(experiment_id, evaluator_version_id, environment_version_id);

-- ═══════════════════════════════════════════
-- Search Policy：Slow Loop 的一等对象
-- ═══════════════════════════════════════════
CREATE TABLE IF NOT EXISTS search_policy_version (
    id                  TEXT PRIMARY KEY,
    experiment_id       TEXT REFERENCES experiment(id),
    parent_policy_id    TEXT REFERENCES search_policy_version(id),
    version             INTEGER NOT NULL,
    genome              TEXT NOT NULL,              -- JSON: SearchPolicyGenome
    risk_level          TEXT NOT NULL DEFAULT 'L0',
    status              TEXT NOT NULL DEFAULT 'challenger', -- draft/challenger/champion/rejected/retired
    artifact_hash       TEXT REFERENCES artifact(hash),
    created_at          TEXT DEFAULT (datetime('now')),
    UNIQUE(experiment_id, version)
);

CREATE TABLE IF NOT EXISTS policy_experiment (
    id                  TEXT PRIMARY KEY,
    experiment_id       TEXT NOT NULL REFERENCES experiment(id),
    champion_policy_id  TEXT NOT NULL REFERENCES search_policy_version(id),
    challenger_policy_id TEXT NOT NULL REFERENCES search_policy_version(id),
    evaluation_mode     TEXT NOT NULL,              -- replay/canary/live
    budget_spec         TEXT NOT NULL,              -- JSON: equal token/compute/time budget
    replay_snapshot_hash TEXT REFERENCES artifact(hash),
    status              TEXT NOT NULL DEFAULT 'queued',
    promotion_decision  TEXT,
    evidence            TEXT,                       -- JSON
    created_at          TEXT DEFAULT (datetime('now')),
    finished_at         TEXT
);

-- ═══════════════════════════════════════════
-- 轨道 B：策略窗口健康度，而非候选节点分数
-- ═══════════════════════════════════════════
CREATE TABLE IF NOT EXISTS meta_evaluation_window (
    id                  TEXT PRIMARY KEY,
    experiment_id       TEXT NOT NULL REFERENCES experiment(id),
    search_policy_id    TEXT NOT NULL REFERENCES search_policy_version(id),
    generation_start    INTEGER NOT NULL,
    generation_end      INTEGER NOT NULL,
    candidate_count     INTEGER NOT NULL,
    telemetry           TEXT NOT NULL,              -- JSON 原始客观指标
    roi_score           REAL,
    coverage_entropy    REAL,
    memory_effectiveness REAL,
    pollution_ratio     REAL,
    alert_level         TEXT DEFAULT 'ok',
    recommendations     TEXT,                       -- JSON
    should_trigger_meta INTEGER DEFAULT 0,
    created_at          TEXT DEFAULT (datetime('now'))
);

-- ═══════════════════════════════════════════
-- 分层全局记忆（四元组扩展）
-- ═══════════════════════════════════════════
CREATE TABLE IF NOT EXISTS memory_entry (
    id                  TEXT PRIMARY KEY,
    experiment_id       TEXT REFERENCES experiment(id),
    task_id             TEXT,
    task_family         TEXT,
    domain_id           TEXT,
    branch_id           TEXT,
    scope_level         INTEGER NOT NULL,           -- L0 branch / L1 experiment / L2 task family / L3 domain / L4 global
    thought_id          TEXT REFERENCES thought_record(id),
    candidate_id        TEXT REFERENCES candidate(id),
    code_diff_hash      TEXT REFERENCES artifact(hash),
    outcome_summary     TEXT NOT NULL,              -- JSON: metrics/success/failure/reason
    success_flag        INTEGER NOT NULL,
    embedding_code_ref  TEXT,
    embedding_thought_ref TEXT,
    created_at          TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_memory_scope
    ON memory_entry(scope_level, experiment_id, task_id, domain_id);

-- ═══════════════════════════════════════════
-- Prompt 与 Embedding 版本管理
-- ═══════════════════════════════════════════
CREATE TABLE IF NOT EXISTS prompt_version (
    id                  TEXT PRIMARY KEY,
    agent_role          TEXT NOT NULL,
    version             INTEGER NOT NULL,
    content_hash        TEXT NOT NULL REFERENCES artifact(hash),
    parent_id           TEXT REFERENCES prompt_version(id),
    search_policy_id    TEXT REFERENCES search_policy_version(id),
    status              TEXT DEFAULT 'challenger',
    created_at          TEXT DEFAULT (datetime('now')),
    UNIQUE(agent_role, version)
);

CREATE TABLE IF NOT EXISTS embedding_profile (
    id                  TEXT PRIMARY KEY,
    purpose             TEXT NOT NULL,              -- code/thought
    provider            TEXT NOT NULL,
    model               TEXT NOT NULL,
    revision            TEXT,
    dimension           INTEGER NOT NULL,
    normalization       TEXT,
    input_type          TEXT,
    chunking_policy     TEXT,
    collection_path     TEXT NOT NULL,
    created_at          TEXT DEFAULT (datetime('now'))
);

-- ═══════════════════════════════════════════
-- SQLite → zvec 最终一致性 Outbox
-- ═══════════════════════════════════════════
CREATE TABLE IF NOT EXISTS vector_index_job (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type         TEXT NOT NULL,              -- candidate/thought/memory
    entity_id           TEXT NOT NULL,
    embedding_profile_id TEXT NOT NULL REFERENCES embedding_profile(id),
    content_hash        TEXT NOT NULL REFERENCES artifact(hash),
    operation           TEXT NOT NULL DEFAULT 'upsert',
    status              TEXT NOT NULL DEFAULT 'pending',
    attempts            INTEGER DEFAULT 0,
    lease_owner         TEXT,
    lease_expires_at    TEXT,
    last_error          TEXT,
    created_at          TEXT DEFAULT (datetime('now')),
    updated_at          TEXT DEFAULT (datetime('now')),
    UNIQUE(entity_type, entity_id, embedding_profile_id, content_hash, operation)
);

-- ═══════════════════════════════════════════
-- 通用异步任务租约：支持 kill -9 恢复
-- ═══════════════════════════════════════════
CREATE TABLE IF NOT EXISTS job (
    id                  TEXT PRIMARY KEY,
    experiment_id       TEXT NOT NULL REFERENCES experiment(id),
    job_type            TEXT NOT NULL,
    payload              TEXT NOT NULL,
    status              TEXT NOT NULL DEFAULT 'queued',
    attempt              INTEGER DEFAULT 0,
    max_attempts         INTEGER DEFAULT 3,
    lease_owner         TEXT,
    lease_expires_at    TEXT,
    heartbeat_at        TEXT,
    result_ref          TEXT,
    last_error          TEXT,
    created_at          TEXT DEFAULT (datetime('now')),
    updated_at          TEXT DEFAULT (datetime('now'))
);
```

### 4.2 zvec 向量集合与 Adapter

v0.1 的代码继续保留“代码向量”和“思想向量”两个集合，但业务层不再直接依赖 zvec 构造函数和搜索函数的具体形式。所有向量后端通过统一接口接入：

```python
# storage/vector_backend.py
from typing import Protocol, Sequence
from dataclasses import dataclass

@dataclass(frozen=True)
class VectorRecord:
    id: str
    vector: Sequence[float]
    metadata: dict

@dataclass(frozen=True)
class VectorHit:
    id: str
    similarity: float
    metadata: dict

class VectorBackend(Protocol):
    def create_or_open(self, profile: "EmbeddingProfile") -> None: ...
    def upsert(self, profile_id: str, records: list[VectorRecord]) -> None: ...
    def query(
        self,
        profile_id: str,
        vector: Sequence[float],
        top_k: int,
        filters: dict | None = None,
    ) -> list[VectorHit]: ...
    def delete(self, profile_id: str, ids: list[str]) -> None: ...
    def healthcheck(self, profile_id: str) -> dict: ...
```

zvec 的真实初始化、Schema 和查询 API 只存在于 `ZvecBackend` 内。这样 zvec 版本变化不会扩散到 `memory.py`、`novelty.py` 或 Agent 代码。

**索引写入流程**不再直接“双写”：

```text
SQLite transaction:
    insert candidate / thought / memory
    insert vector_index_job(status='pending')
    commit

VectorIndexer:
    claim pending job with lease
    read content by artifact hash
    generate embedding by profile
    idempotent upsert to VectorBackend
    mark indexed
```

**使用场景保持不变，但从单阈值升级为多级判断**：

- Thought 语义初筛：在 `thought` 索引中 top-k 搜索；
- 代码语义初筛：在 `code` 索引中搜索相似实现；
- 跨分支融合：在高任务分数候选中寻找“机制互补、血缘较远、行为特征不同”的父代；
- RAG 记忆检索：FTS5 + 向量召回 + scope filter + rerank；
- 新颖性门：Embedding 相似仅作为第一阶段，不直接一票否决。

```text
Embedding 高相似
    ↓
思想机制标签 / AST 结构 / API 依赖检查
    ↓
可选：行为签名或小样本执行
    ↓
必要时 LLM novelty judge
    ↓
REJECT / ALLOW / ALLOW_WITH_PENALTY
```

---

## 五、核心接口定义（Python Protocol）

### 5.1 轨道 A：任务评估器

v0.1 中 `Sandbox.execute(code)` 与 `TaskEvaluator.evaluate(EvalInput)` 的职责存在重叠。v0.2 保留 TaskEvaluator 插件化，但调整为：**Evaluator 描述怎么评，Sandbox 统一负责执行，Evaluator 再解析结果**。

```python
# eval/task_evaluator.py
from typing import Protocol, runtime_checkable
from dataclasses import dataclass, field
from pathlib import Path

@dataclass(frozen=True)
class CandidateArtifact:
    candidate_id: str
    source_hash: str
    manifest_hash: str | None
    language: str
    entrypoint: str | None = None

@dataclass(frozen=True)
class EvaluationContext:
    experiment_id: str
    evaluator_version_id: str
    environment_version_id: str
    seed: int | None = None
    split_name: str = "default"
    extra_context: dict = field(default_factory=dict)

@dataclass(frozen=True)
class MountSpec:
    source: str
    target: str
    read_only: bool = True

@dataclass(frozen=True)
class CommandSpec:
    argv: list[str]
    cwd: str = "/workspace"
    timeout_sec: float = 30.0
    env: dict[str, str] = field(default_factory=dict)

@dataclass(frozen=True)
class EvaluationPlan:
    commands: list[CommandSpec]
    mounts: list[MountSpec] = field(default_factory=list)
    expected_outputs: list[str] = field(default_factory=list)
    resource_profile: str = "default"
    network_access: bool = False

@dataclass(frozen=True)
class SandboxExecutionResult:
    return_codes: list[int]
    stdout: str
    stderr: str
    output_artifacts: dict[str, str]       # path -> artifact hash
    execution_time_ms: float
    cpu_time_ms: float
    memory_peak_kb: int
    timed_out: bool = False
    policy_violation: str | None = None

@dataclass(frozen=True)
class EvalOutput:
    score: float
    metrics: dict[str, float]
    passed: bool
    failure_reason: str = ""
    confidence: float | None = None

@runtime_checkable
class TaskEvaluator(Protocol):
    """
    用户实现此接口。
    Evaluator 只能构造声明式 EvaluationPlan 和解析 Sandbox 结果，
    不能在宿主机直接运行候选代码。
    """

    @property
    def version_id(self) -> str: ...

    def build_plan(
        self,
        candidate: CandidateArtifact,
        context: EvaluationContext,
    ) -> EvaluationPlan:
        ...

    def parse_result(
        self,
        result: SandboxExecutionResult,
        context: EvaluationContext,
    ) -> EvalOutput:
        ...

    def get_baseline(self) -> float:
        ...
```

**用户实现示例**（高频交易场景）保持原意，但不再直接调用 `subprocess.run()`：

```python
class LatencyEvaluator:
    version_id = "latency-evaluator@1.0.0"

    def build_plan(self, candidate, context) -> EvaluationPlan:
        return EvaluationPlan(
            commands=[
                CommandSpec(argv=["cmake", "-S", ".", "-B", "build"]),
                CommandSpec(argv=["cmake", "--build", "build", "-j2"]),
                CommandSpec(
                    argv=["./build/bench", "--orders=100000", "--json=latency.json"],
                    timeout_sec=10.0,
                ),
            ],
            expected_outputs=["latency.json"],
            network_access=False,
            resource_profile="cpp-benchmark",
        )

    def parse_result(self, result, context) -> EvalOutput:
        if result.timed_out or any(code != 0 for code in result.return_codes):
            return EvalOutput(
                score=0.0,
                metrics={},
                passed=False,
                failure_reason=result.stderr[-4000:],
            )
        latency = parse_latency_artifact(result.output_artifacts["latency.json"])
        return EvalOutput(
            score=1.0 / latency,
            metrics={"latency_us": latency},
            passed=latency < 100,
        )

    def get_baseline(self) -> float:
        return 1.0 / 50.0
```

### 5.1.1 评估语义不可变边界

Meta-Agent 和 `infra_adapter.py` 必须遵守以下三级权限：

```text
L2：默认永久禁止自动修改
- Task semantics
- Correctness tests
- Hidden test set / dataset content
- Metric definition
- Score aggregation rule
- 通过/失败的语义阈值

L1：允许提出 Challenger，但必须版本化并 Replay/Canary
- Timeout schedule
- Progressive evaluation stages
- Benchmark repetition count
- Resource allocation
- Build cache
- Compilation flags（不得改变任务语义）

L0：可自动调整并记录
- 日志格式
- tracing
- 非语义性结果采集
- 临时目录和缓存回收
```

任何 L1 变更都必须：

1. 创建新的 `ExecutionEnvironmentVersion`；
2. 重跑 baseline；
3. 重跑当前 elite archive 的固定样本；
4. 检查分数和候选排名稳定性；
5. 通过门槛后才晋升，否则回滚。

### 5.2 轨道 B：自评估器

v0.1 的 `SelfEvaluator.assess()` 继续作为外观接口，但内部拆分为三部分，避免一个 LLM 同时承担观察、评分、诊断和决策：

```text
TelemetryAggregator   # 计算客观、可复现指标
HealthPolicy          # 规则与统计判定
MetaPlanner           # 解释原因并提出受控动作
```

```python
# eval/self_evaluator.py
from typing import Protocol, runtime_checkable
from dataclasses import dataclass, field

@dataclass(frozen=True)
class HealthInput:
    experiment_id: str
    search_policy_id: str
    generation_start: int
    generation_end: int
    candidates: list[dict]
    evaluation_runs: list[dict]
    graph_stats: dict
    model_call_stats: dict
    compute_stats: dict
    memory_stats: dict
    context_stats: dict
    novelty_stats: dict
    budget_state: dict

@dataclass(frozen=True)
class HealthOutput:
    roi_score: float
    coverage_entropy: float
    memory_effectiveness: float
    pollution_ratio: float
    alert_level: str                 # ok / warn / critical
    recommendations: list[str]
    should_trigger_meta: bool
    evidence: dict = field(default_factory=dict)

class TelemetryAggregator(Protocol):
    def aggregate(self, inp: HealthInput) -> dict: ...

class HealthPolicy(Protocol):
    def assess(self, telemetry: dict) -> HealthOutput: ...

class MetaPlanner(Protocol):
    def propose(
        self,
        health: HealthOutput,
        champion_policy: "SearchPolicyGenome",
        history: list[dict],
    ) -> list["MetaAction"]:
        ...

@runtime_checkable
class SelfEvaluator(Protocol):
    """框架内置默认实现，用户可以覆盖聚合器或健康策略。"""
    def assess(self, inp: HealthInput) -> HealthOutput: ...
```

#### 5.2.1 系统健康指标的可计算定义

**算力 ROI** 不再只计算“每 1000 token 的单次分数提升”，而使用窗口化成本归一化前沿提升：

\[
\mathrm{ROI}_t =
\frac{\Delta \mathrm{HV}_t}
{\lambda_1 C_{\mathrm{API}} +
 \lambda_2 C_{\mathrm{compute}} +
 \lambda_3 T_{\mathrm{wall}}}
\]

- 多目标任务使用 Pareto 前沿 Hypervolume Improvement；
- 单目标任务使用带置信区间的 best-score improvement；
- API 费用、CPU/GPU 时间和墙钟时间分别记录，不只看 token。

**搜索空间覆盖率**由多种信号组成：

```text
thought_cluster_entropy
knn_distance_distribution
ast_feature_coverage
behavior_signature_entropy
mechanism_tag_coverage
branch_balance
```

熵需按样本数量和有效簇数归一化，不能直接对 cosine novelty 列表计算 Shannon entropy。

**记忆有效性**使用可观测量：

```text
retrieved_memory_count
memory_citation_rate
memory_adoption_rate
duplicate_attempt_reduction
retrieved_failure_recurrence_rate
memory_ablation_gain
```

系统可以按低频率、固定预算执行“有记忆 vs 无记忆”的小规模 A/B，以估计真正增益。

**上下文污染度**由以下信号估计：

```text
semantic_duplicate_ratio
unused_retrieval_ratio
stale_memory_ratio
context_ablation_instability
historical_failure_recurrence
prompt_token_marginal_gain
```

### 5.3 Agent 基类与编排

原有 Director / Coder / Critic / MetaAgent 分工保持不变，但上下文加入策略、评估环境和来源版本：

```python
# agents/base.py
from typing import Protocol
from dataclasses import dataclass, field

@dataclass(frozen=True)
class AgentContext:
    experiment_id: str
    task_id: str
    generation: int
    island_id: str | None
    parent_candidate_ids: list[str]
    parent_thoughts: list[str]
    parent_artifact_hashes: list[str]
    memory_hits: list[dict]
    domain_hints: list[str]
    search_policy_id: str
    evaluator_version_id: str
    environment_version_id: str
    prompt_version_id: str
    system_prompt: str
    model: str
    provenance: dict = field(default_factory=dict)

@dataclass(frozen=True)
class ThoughtOutput:
    thought: str
    rationale: str
    risk_notes: str
    confidence: float
    mechanism_tags: list[str] = field(default_factory=list)

@dataclass(frozen=True)
class CodeOutput:
    diff: str
    full_code: str
    explanation: str
    touched_files: list[str] = field(default_factory=list)

class DirectorAgent(Protocol):
    def evolve_thought(self, ctx: AgentContext) -> ThoughtOutput: ...

class CoderAgent(Protocol):
    def generate_code(self, ctx: AgentContext, thought: ThoughtOutput) -> CodeOutput: ...

class CriticAgent(Protocol):
    def review(self, code: CodeOutput, thought: ThoughtOutput) -> tuple[bool, str]: ...

class MetaAgent(Protocol):
    def optimize(
        self,
        health: HealthOutput,
        champion_policy: "SearchPolicyGenome",
        history: list[dict],
    ) -> list["MetaAction"]:
        ...
```

### 5.4 进化引擎

```python
# engine/scheduler.py
from dataclasses import dataclass, field

@dataclass
class EvolutionConfig:
    max_generations: int = 50
    population_size: int = 8
    island_count: int = 4
    novelty_threshold: float = 0.92       # 仅为一级初筛阈值
    novelty_retry_limit: int = 3
    router_algorithm: str = "sliding_window_ucb"
    ucb_c: float = 1.414
    temperature: float = 0.7
    mutation_rate: float = 0.3
    crossover_rate: float = 0.15
    max_stagnation_gens: int = 5
    token_budget: int = 2_000_000
    compute_budget_sec: float | None = None
    sandbox_timeout: float = 30.0
    health_window_gens: int = 3
    meta_canary_budget_ratio: float = 0.1

class EvolutionEngine:
    def __init__(
        self,
        config: EvolutionConfig,
        task_evaluator: TaskEvaluator,
        self_evaluator: SelfEvaluator,
        director: DirectorAgent,
        coder: CoderAgent,
        critic: CriticAgent,
        meta: MetaAgent,
        sandbox: "SandboxBackend",
        artifact_store: "ArtifactStore",
        graph_store: "GraphStore",
        vector_backend: "VectorBackend",
        plugins: list["Plugin"] | None = None,
    ):
        ...

    def run(self, initial_code: str, task_name: str) -> "EvolutionResult":
        """启动 Fast Loop；按窗口调用 Slow Loop。支持幂等恢复。"""
        ...

    def step(self) -> "GenerationResult":
        """执行单代候选进化。"""
        ...

    def assess_policy_window(self) -> HealthOutput:
        """聚合当前 SearchPolicyVersion 在窗口内的轨道B指标。"""
        ...

    def run_policy_challenger(self, actions: list["MetaAction"]) -> "PolicyExperimentResult":
        """创建 Challenger，执行等预算 Replay/Canary，不直接覆盖 Champion。"""
        ...

    def resume(self, experiment_id: str) -> "EvolutionResult":
        """恢复已提交状态，重新认领租约过期任务。"""
        ...

@dataclass(frozen=True)
class EvolutionResult:
    best_candidate_id: str
    best_artifact_hash: str
    best_score: float
    champion_policy_id: str
    total_generations: int
    total_tokens: int
    total_cost_usd: float
    total_compute_sec: float
    evolution_graph_path: str
```

### 5.4.1 Search Policy Genome

```python
# meta/policy_genome.py
from dataclasses import dataclass

@dataclass(frozen=True)
class SearchPolicyGenome:
    parent_selector: str
    mutation_mix: dict[str, float]
    crossover_policy: str
    retrieval_budget: int
    memory_scope_weights: dict[str, float]
    context_pruning_policy: str
    novelty_policy: str
    model_routing_policy: str
    director_prompt_version: str
    coder_prompt_version: str
    critic_prompt_version: str
    temperature_schedule: str
    island_migration_policy: str
    backtracking_policy: str
```

系统维护：

- 一个当前 `Champion Policy`；
- 多个待验证 `Challenger Policy`；
- 相同任务状态、相同数据快照和相同预算下的比较；
- 达到统计门槛后晋升；
- 失败或退化时完整回滚策略、Prompt 和超参数快照。

### 5.5 模型路由（角色条件化的非平稳 Bandit）

v0.1 的 UCB1 保留为基础能力，但不再固定“前 30% heavy、后 70% light”。路由输入包含 Agent 角色、搜索状态、任务特征和预算状态。

```python
# agents/router.py
from dataclasses import dataclass

@dataclass(frozen=True)
class ModelSlot:
    name: str
    tier: str
    cost_per_1k_input: float
    cost_per_1k_output: float
    avg_latency_ms: float
    capabilities: set[str]

@dataclass(frozen=True)
class RouteContext:
    role: str                       # director/coder/critic/meta
    generation: int
    stagnation_level: float
    novelty_deficit: float
    implementation_difficulty: float
    remaining_token_ratio: float
    remaining_compute_ratio: float
    required_capabilities: set[str]

class ModelRouter:
    """Sliding-window UCB / Discounted UCB / Thompson 可插拔路由。"""

    def __init__(self, slots: list[ModelSlot], algorithm: str = "sliding_window_ucb"):
        ...

    def select(self, ctx: RouteContext) -> str:
        ...

    def update(self, model: str, role: str, reward: dict[str, float]) -> None:
        ...
```

角色奖励分离：

```text
Director:
    thought adoption
    mechanism novelty
    downstream frontier contribution

Coder:
    patch apply rate
    compile rate
    test pass rate
    realized performance gain

Critic:
    defect recall
    false rejection rate
    evaluator cost saved
```

### 5.6 领域插件

原有插件接口保留，但 `post_eval_hook` 只能补充领域指标或发出约束告警，不能静默改写任务主分数：

```python
# plugins/base.py
from typing import Protocol

class Plugin(Protocol):
    name: str
    version: str

    def get_domain_hints(self, task_description: str) -> list[str]:
        ...

    def get_rag_corpus(self) -> list[dict] | None:
        ...

    def enrich_evaluation(
        self,
        candidate: CandidateArtifact,
        output: EvalOutput,
    ) -> dict:
        """返回附加指标、约束告警和解释；不得更改不可变评分语义。"""
        ...
```

---

## 六、核心工作流（单代 + 策略窗口）

### 6.1 Fast Loop：单代候选进化

原 v0.1 的 11 步流程保留，并在执行、存储和评估边界上补齐：

```text
┌──────────────────────────────────────────────────────────────────┐
│ Generation N                                                     │
│                                                                  │
│ 1. Router.select(RouteContext) → 按角色分配模型                  │
│                                                                  │
│ 2. ParentSelector → 选择一个或多个父代                            │
│    ├── exploitation：高分 / Pareto elite                          │
│    ├── exploration：低访问但有潜力节点                            │
│    └── crossover：血缘远、机制互补的跨分支父代                    │
│                                                                  │
│ 3. Director.evolve_thought(ctx)                                  │
│    ├── 按 L0~L4 scope 混合检索 memory                             │
│    ├── 加载父代、兄弟和引用分支摘要                               │
│    └── 生成 ThoughtOutput + mechanism_tags                        │
│                                                                  │
│ 4. MultiStageNoveltyGate                                         │
│    ├── Embedding 一级筛查                                        │
│    ├── 思想机制 / AST / API 结构检查                              │
│    ├── 可选行为签名                                               │
│    └── REJECT / ALLOW / ALLOW_WITH_PENALTY                       │
│                                                                  │
│ 5. Coder.generate_code(ctx, thought) → CodeOutput                │
│                                                                  │
│ 6. Critic.review(code, thought)                                  │
│    ├── 语法、补丁可应用性、静态逻辑和权限检查                     │
│    └── 不通过 → 打回 Coder（最多配置次数）                         │
│                                                                  │
│ 7. ArtifactStore                                                 │
│    ├── 保存 source / diff / manifest                              │
│    └── SQLite 事务写 Candidate + Lineage + vector_index_job       │
│                                                                  │
│ 8. TaskEvaluator.build_plan(...) → EvaluationPlan               │
│                                                                  │
│ 9. SandboxBackend.execute(plan)                                  │
│    ├── 默认 Docker：禁网、只读、降权、限 CPU/内存/PID             │
│    └── 捕获 stdout/stderr/时间/内存/输出 Artifact                  │
│                                                                  │
│ 10. TaskEvaluator.parse_result(...) → EvalOutput                 │
│     ├── 写入 EvaluationRun                                       │
│     └── Plugin.enrich_evaluation() 添加附加指标                   │
│                                                                  │
│ 11. 更新 Candidate Archive / Search State / Memory / Router       │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

### 6.2 Slow Loop：策略窗口评估与元进化

```text
每 health_window_gens 代或发生 critical alert：

1. TelemetryAggregator
   ├── 聚合候选前沿提升、模型成本、执行成本
   ├── 聚合覆盖率、分支平衡、重复率
   ├── 聚合记忆使用和上下文污染信号
   └── 绑定当前 SearchPolicyVersion

2. HealthPolicy.assess
   ├── 生成 HealthOutput
   └── 写入 MetaEvaluationWindow

3. MetaPlanner.propose
   ├── 只生成允许的 MetaAction
   └── 每个动作标注 L0 / L1 / L2 风险

4. Governance
   ├── L0：自动创建 Challenger
   ├── L1：强制 Replay / Canary
   └── L2：自动拒绝，除非人类显式修改不可变配置

5. PolicyExperiment
   ├── Champion 与 Challenger 使用相同快照和预算
   ├── 比较任务前沿、成本、稳定性和健康度
   └── Promote / Reject / Rollback
```

### 6.3 元进化动作分级

```text
L0 自动允许
- 调整 temperature schedule
- 调整父代采样和岛屿迁移
- 调整检索数量、memory scope 权重
- 调整 mutation mix / crossover rate
- 切换模型路由算法或模型分配

L1 必须 Replay / Canary
- 修改 Director / Coder / Critic Prompt
- 修改上下文裁剪策略
- 修改 crossover / backtracking 算法
- 修改搜索控制器实现
- 修改 timeout schedule、渐进式评估和编译参数

L2 默认禁止
- 修改评分公式
- 修改正确性测试
- 修改隐藏数据
- 修改任务语义
- 为候选代码开放宿主机或任意网络
- 通过异常吞噬、跳过测试等方式改变通过含义
```

---

## 七、SQLite 图操作封装

原有 `GraphStore` 保留，但从 `parent_id` 回溯改为 `candidate_lineage` 多父代图，并显式管理搜索统计：

```python
# storage/graph_store.py
import sqlite3
import networkx as nx

class GraphStore:
    """SQLite Candidate 图 ↔ NetworkX 内存图双向同步。"""

    def __init__(self, db_path: str):
        self.conn = sqlite3.connect(db_path)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.execute("PRAGMA busy_timeout=5000")

    def add_candidate(self, candidate: dict, parents: list[dict]) -> str:
        """单事务插入 Candidate、多父代 Lineage、初始 SearchState 和 Outbox。"""
        ...

    def add_reference_edge(
        self,
        src: str,
        dst: str,
        reference_type: str,
        detail: dict,
    ) -> None:
        ...

    def update_search_state(self, candidate_id: str, delta: dict) -> None:
        ...

    def load_subgraph(
        self,
        root_ids: list[str],
        max_depth: int = 10,
        include_reference_edges: bool = False,
    ) -> nx.MultiDiGraph:
        ...

    def get_stagnant_branches(
        self,
        experiment_id: str,
        threshold_gens: int,
    ) -> list[str]:
        ...

    def get_best_paths(
        self,
        experiment_id: str,
        evaluator_version_id: str,
        environment_version_id: str,
        top_k: int = 1,
    ) -> list[list[str]]:
        """多父代 DAG 中返回最优贡献路径，不假定唯一 parent。"""
        ...

    def get_diverse_elites(
        self,
        experiment_id: str,
        island_id: str | None,
        top_k: int,
    ) -> list[str]:
        ...

    def export_graphml(self, experiment_id: str, path: str) -> None:
        ...
```

图中两类边必须区分：

```text
Lineage Edge：候选真正由哪些父代产生
Reference Edge：生成时借鉴、检索或修复引用了哪些历史候选
```

这避免把“看过某个候选”错误地解释成“由它遗传产生”。

---

## 八、zvec 向量操作封装

v0.1 的 `VectorStore` 继续作为上层 Facade，但其内部改为 `VectorBackend + EmbeddingProfile + Outbox`：

```python
# storage/vector_store.py
class VectorStore:
    def __init__(
        self,
        backend: VectorBackend,
        embedding_service: "EmbeddingService",
        profile_registry: "EmbeddingProfileRegistry",
        memory_store: "MemoryStore",
    ):
        self.backend = backend
        self.embedding_service = embedding_service
        self.profile_registry = profile_registry
        self.memory_store = memory_store

    def semantic_candidates(
        self,
        text: str,
        purpose: str,
        scope: dict,
        top_k: int = 10,
    ) -> list[VectorHit]:
        ...

    def check_novelty(
        self,
        thought: ThoughtOutput,
        code: CodeOutput | None,
        scope: dict,
        threshold: float = 0.92,
    ) -> "NoveltyDecision":
        """Embedding 仅一级初筛；最终由多阶段 NoveltyGate 决定。"""
        ...

    def find_diverse_high_scorers(
        self,
        experiment_id: str,
        exclude_ids: list[str],
        top_k: int = 3,
    ) -> list[str]:
        ...

    def rag_retrieve(
        self,
        query: str,
        scope_weights: dict[str, float],
        top_k: int = 5,
    ) -> list[dict]:
        """FTS5 + Vector + scope filter + rerank。"""
        ...
```

### 8.1 分层记忆检索

```text
L0 当前分支：最具体，避免重复当前分支错误
L1 当前实验：共享同一任务的有效经验
L2 任务族：相似 evaluator / 数据结构 / 目标函数
L3 领域：Quant、Geo、AutoML 等领域先验
L4 跨领域：通用算法与工程经验
```

Director 的策略基因决定各层预算和权重；检索结果必须携带来源、作用域、历史结果和被采用情况，便于计算记忆有效性。

### 8.2 Embedding Profile 迁移原则

任何 Embedding 模型变化都不得静默覆盖原索引。应创建新 `EmbeddingProfile`：

```text
provider
model
revision
dimension
normalization
input_type
chunking_policy
collection_path
```

重建完成前，新旧 Profile 可并行查询；达到覆盖率后再切换默认 Profile。

---

## 九、沙箱执行器

v0.1 的 `Sandbox` 改为后端协议，保留轻量 subprocess 实现，但明确它只用于可信模式。

```python
# sandbox/base.py
from typing import Protocol
from dataclasses import dataclass, field

@dataclass(frozen=True)
class SandboxPolicy:
    timeout_sec: float = 30.0
    mem_limit_mb: int = 512
    cpu_limit: float = 1.0
    pids_limit: int = 64
    network_mode: str = "none"
    read_only_root: bool = True
    run_as_non_root: bool = True
    drop_capabilities: bool = True
    no_new_privileges: bool = True
    tmpfs_mb: int = 256
    allowed_env: set[str] = field(default_factory=set)

class SandboxBackend(Protocol):
    @property
    def environment_version_id(self) -> str: ...

    def execute(
        self,
        plan: EvaluationPlan,
        candidate: CandidateArtifact,
        policy: SandboxPolicy,
    ) -> SandboxExecutionResult:
        ...
```

### 9.1 默认 DockerBackend

```python
# sandbox/docker_backend.py
class DockerBackend:
    """
    默认候选执行后端。

    最低安全配置：
    - network=none
    - read_only root filesystem
    - cap_drop=ALL
    - no-new-privileges
    - non-root UID/GID
    - pids / memory / cpu / timeout limits
    - 独立临时工作区和 tmpfs
    - 只读挂载数据集
    - 环境变量白名单，不继承 API Key
    - 固定 image digest 和 dependency lock
    """
    ...
```

### 9.2 TrustedSubprocessBackend

```python
# sandbox/subprocess_backend.py
class TrustedSubprocessBackend:
    """
    仅供用户明确确认的可信代码、本地单元测试或开发调试。
    resource.setrlimit 仅在支持的平台上限制部分资源，
    不提供文件系统、网络、权限或系统调用隔离。
    """
    ...
```

### 9.3 Progressive Evaluation

为减少 Timeout 误杀，可以调整**评估基础设施**，但不得修改任务语义：

```text
Stage 0：静态语法 / Patch apply / Compile smoke test
Stage 1：小样本、短 timeout correctness
Stage 2：完整 correctness
Stage 3：正式 benchmark，多次重复与置信区间
```

任何阶段变化都生成新的 `ExecutionEnvironmentVersion`，并按第 5.1.1 节重跑 baseline 和 elite archive。

---

## 十、配置文件（`omnievolve.toml`）

```toml
[evolution]
max_generations = 50
population_size = 8
island_count = 4
novelty_threshold = 0.92        # 仅用于一级 Embedding 筛查
novelty_retry_limit = 3
mutation_rate = 0.3
crossover_rate = 0.15
max_stagnation_gens = 5
token_budget = 2_000_000
compute_budget_sec = 0          # 0 表示不单独限制
health_window_gens = 3

[selection]
parent_selector = "progressive_mcgs"
tournament_size = 3
pareto_enabled = true
island_migration_interval = 5

[models]
# 名称只是示例；实际部署由用户选择可用模型
heavy = ["reasoning-model-primary", "reasoning-model-secondary"]
light = ["fast-model-primary", "fast-model-secondary"]

[models.routing]
algorithm = "sliding_window_ucb"  # sliding_window_ucb / discounted_ucb / thompson
window_size = 50
ucb_c = 1.414
cost_weight = 0.2
latency_weight = 0.1
role_conditioned = true

[embedding.code]
provider = "voyage"
model = "voyage-code-3"
revision = "default"
dimension = 1024
normalization = "provider_default"
input_type = "document"

[embedding.thought]
provider = "local"
model = "bge-m3"
revision = "default"
dimension = 1024
normalization = "l2"
input_type = "document"

[novelty]
embedding_gate = true
ast_gate = true
behavior_gate = false
llm_judge_on_borderline = true
borderline_low = 0.88
borderline_high = 0.96

[sandbox]
backend = "docker"             # docker / trusted_subprocess / hardened
timeout_sec = 30
mem_limit_mb = 512
cpu_limit = 1.0
pids_limit = 64
network_mode = "none"
read_only_root = true
run_as_non_root = true
drop_capabilities = true
no_new_privileges = true
language = "python"

[sandbox.docker]
image = "omnievolve/python-runner@sha256:<digest>"
tmpfs_mb = 256
inherit_host_env = false

[storage]
db_path = ".omnievolve/omnievolve.db"
vector_dir = ".omnievolve/vectors"
artifact_dir = ".omnievolve/artifacts"
export_dir = ".omnievolve/exports"

[storage.jobs]
lease_sec = 120
heartbeat_sec = 20
max_attempts = 3

[memory]
default_top_k = 8
scope_weights = { L0 = 1.0, L1 = 0.9, L2 = 0.6, L3 = 0.4, L4 = 0.2 }
ablation_interval_gens = 10

[self_evaluator]
roi_warn_threshold = 0.001
entropy_warn_threshold = 0.35
stagnation_trigger = 3
window_gens = 3
require_confidence_interval = true

[meta_evolution]
enabled = true
prompt_mutation_rate = 0.2
meta_canary_budget_ratio = 0.1
promotion_min_gain = 0.02
promotion_max_regression = 0.005
require_replay_for_l1 = true
auto_apply_l0 = true
allow_l2_actions = false

[evaluation_governance]
immutable_task_semantics = true
immutable_correctness_tests = true
immutable_hidden_data = true
immutable_score_formula = true
allow_environment_adaptation = true
require_baseline_recheck = true
require_elite_rank_stability = true
```

---

## 十一、CLI 入口

原有命令保留，增加策略、审计和恢复检查：

```python
# cli.py
import typer
app = typer.Typer()

@app.command()
def run(
    task: str = typer.Argument(..., help="任务描述 or 初始代码文件路径"),
    config: str = typer.Option("omnievolve.toml", "--config", "-c"),
    evaluator: str = typer.Option(..., "--evaluator", "-e"),
    resume: str = typer.Option(None, "--resume"),
    generations: int = typer.Option(None, "--gens", "-g"),
    trusted: bool = typer.Option(False, "--trusted", help="显式启用非隔离 subprocess 模式"),
):
    """启动候选进化；按健康窗口自动运行受控策略进化。"""
    ...

@app.command()
def status(experiment_id: str):
    """查看进化进度、任务租约、Champion Policy 和健康状态。"""
    ...

@app.command()
def export(experiment_id: str, format: str = "graphml"):
    """导出进化图、策略谱系或审计报告。"""
    ...

@app.command()
def best(experiment_id: str):
    """输出最优 Candidate Artifact 和对应评估版本。"""
    ...

@app.command()
def policy(experiment_id: str):
    """查看 Champion / Challenger、策略基因和晋升证据。"""
    ...

@app.command()
def audit(experiment_id: str):
    """检查 Artifact 哈希、评估器版本、环境版本和缺失向量索引。"""
    ...

@app.command()
def recover(experiment_id: str, dry_run: bool = True):
    """扫描租约过期任务、未完成 Outbox 和孤立 Artifact。"""
    ...
```

**使用方式**：

```bash
# 默认安全模式：DockerBackend
omnievolve run ./initial_code.py \
  --evaluator my_project.evaluators:LatencyEvaluator \
  --config omnievolve.toml \
  --gens 30

# 断点续跑
omnievolve run ./initial_code.py \
  --evaluator my_project.evaluators:LatencyEvaluator \
  --resume exp_a3f8c2

# 仅在明确可信时启用 subprocess
omnievolve run ./trusted_code.py \
  --evaluator my_project.evaluators:UnitTestEvaluator \
  --trusted

# 查看状态、策略与审计
omnievolve status exp_a3f8c2
omnievolve policy exp_a3f8c2
omnievolve audit exp_a3f8c2

# 导出候选图或策略谱系
omnievolve export exp_a3f8c2 --format graphml
```

---

## 十二、关键设计决策记录（ADR）

| # | 决策 | 理由 | 替代方案（放弃或降级） |
|---|------|------|------------------------|
| 1 | SQLite 单文件存图和元数据 | 低运维、ACID、Python 内置；10 万级候选足够；通过 job lease 解决恢复 | Neo4j（需 server，首版不需要） |
| 2 | Artifact 使用本地内容寻址存储 | 代码、Diff、日志和输出可去重、校验、复现；SQLite 只存引用 | 将完整代码和二进制塞入 `evo_node` |
| 3 | zvec 通过 Adapter 接入 | 嵌入式 ANN，同时隔离 API 变化；core 可回退 NumPy | 业务层直接绑定 zvec 构造与查询 API |
| 4 | SQLite Outbox 驱动向量索引 | SQLite 与 zvec 无法共享事务；Outbox 提供幂等最终一致性 | 事务外直接双写 SQLite + zvec |
| 5 | NetworkX 做限定子图算法 | MCTS/融合需要遍历；只加载任务相关子图，结果回写 | 纯 SQL 递归 CTE；常驻独立图数据库 |
| 6 | Docker 为默认沙箱 | 提供文件系统、网络、权限和资源隔离；不继承 API Key | `subprocess + rlimit` 作为默认“安全沙箱” |
| 7 | Trusted subprocess 仅显式开启 | 保留轻量开发体验，但不虚假承诺安全性或跨平台一致性 | 完全删除 subprocess 模式 |
| 8 | Evaluator 构造计划，Sandbox 执行 | 消除双重执行职责；禁止 Evaluator 绕过隔离执行候选代码 | Evaluator 内部直接 `subprocess.run()` |
| 9 | Task Evaluator 语义核心不可变 | 防止 reward hacking、跳过测试和修改评分目标 | Meta-Agent 自动重写任务评分 Harness |
| 10 | Evaluation Infrastructure Adaptation 取代 Harness Self-Rewriting | 允许优化超时、缓存和渐进执行，但必须版本化和重评 | 无限制自修改评估器 |
| 11 | Candidate / EvaluationRun / PolicyVersion 解耦 | 同一代码可在不同 seed、环境和评估版本下重复运行 | 把 score、latency、memory 全塞入节点 |
| 12 | 多父代 Lineage 为唯一血缘事实 | 支持 crossover，避免 `parent_id` 与 edge 表不一致 | 单一 `parent_id` + 重复 edge 真相 |
| 13 | 健康度绑定策略窗口 | ROI、覆盖率和污染度属于搜索过程，不属于单个候选 | `candidate.health_score` |
| 14 | SearchPolicyVersion 是一等对象 | 支持 Champion-Challenger、Replay、晋升和完整回滚 | 发现告警后直接原地改参数 |
| 15 | 角色条件化非平稳 Bandit | 进化奖励随阶段变化，Director/Coder/Critic 贡献不同 | 固定前 30% heavy、后 70% light |
| 16 | Prompt 版本化存 Artifact + SQLite | 元进化需要内容哈希、回滚和 A/B 证据 | Prompt 写死在代码里 |
| 17 | TOML 配置 | 人类可读、可 git 追踪 | YAML / JSON |
| 18 | 元进化动作 L0/L1/L2 分级 | 自动化能力与安全边界同时存在 | Meta-Agent 获得无边界自修改权限 |

---

## 十三、依赖清单（`pyproject.toml` 核心）

默认依赖保持克制，Docker、zvec、本地 Embedding 和高级调优按组安装：

```toml
[project]
name = "omnievolve"
requires-python = ">=3.11"
dependencies = [
    "litellm>=1.40",
    "networkx>=3.2",
    "pydantic>=2.5",
    "pydantic-settings>=2.1",
    "typer>=0.9",
    "rich>=13.0",
    "numpy>=1.26",
]

[project.optional-dependencies]
vector = [
    "zvec>=0.3",
]
local-embed = [
    "sentence-transformers>=2.3",
]
docker = [
    "docker>=7.0",
]
viz = [
    "pyvis>=0.3",
]
tuning = [
    "optuna>=3.6",
]
dev = [
    "pytest>=8.0",
    "pytest-xdist>=3.5",
    "hypothesis>=6.100",
    "ruff>=0.5",
    "mypy>=1.10",
]

[project.scripts]
omnievolve = "omnievolve.cli:app"
```

安装示例：

```bash
# 核心开发模式
pip install omnievolve

# 推荐本地完整模式
pip install "omnievolve[vector,local-embed,docker]"

# 开发与测试
pip install "omnievolve[vector,docker,dev]"
```

---

## 十四、下一步（阶段 3：任务拆解）

v0.1 的 S1—S9 仍然保留，但按依赖关系调整范围和顺序。首版目标不是一次实现所有元进化能力，而是先得到一个**可信、可恢复、可复现、能稳定执行数百次变异**的底座。

### Phase 1：可运行、可信的进化底座

| Sprint | 交付物 | 参考工作量 |
|--------|--------|-----------|
| S1 | SQLite v0.2 schema、迁移、Artifact Store、内容哈希、事务封装 | 4–5d |
| S2 | SandboxBackend、默认 DockerBackend、TrustedSubprocessBackend、ExecutionEnvironmentVersion | 4–6d |
| S3 | TaskEvaluator `build_plan/parse_result`、Evaluator Registry、demo evaluator、EvaluationRun | 3–4d |
| S4 | Candidate / Lineage / SearchState、基础 scheduler、job lease、kill -9 恢复 | 5–7d |

**Phase 1 验收**：

```text
- 单任务连续执行 ≥500 个候选不丢状态
- kill -9 后不重复提交已完成 EvaluationRun
- 租约过期任务可重新认领
- 候选代码默认无法访问宿主机 API Key 和网络
- 任一结果可还原到 Artifact、Evaluator、Environment、Seed
```

### Phase 2：长程搜索与记忆

| Sprint | 交付物 | 参考工作量 |
|--------|--------|-----------|
| S5 | Director / Coder / Critic、LiteLLM 调用记录、PromptVersion | 4–5d |
| S6 | EmbeddingProfile、VectorBackend、zvec Adapter、Outbox Indexer、FTS5 混合检索 | 4–6d |
| S7 | 分层 Memory L0~L4、多阶段 NoveltyGate、岛屿搜索、跨分支融合 | 5–7d |

**Phase 2 验收**：

```text
- Embedding 模型更换不会覆盖旧索引
- SQLite 与向量索引中断后可自动修复
- 新颖性拒绝不会只由单一 cosine 阈值决定
- 可追踪每条记忆是否被检索、引用、采用及其结果
```

### Phase 3：过程评估与安全自适应

| Sprint | 交付物 | 参考工作量 |
|--------|--------|-----------|
| S8 | TelemetryAggregator、HealthPolicy、ROI/覆盖率/污染度/记忆指标、角色路由 | 5–7d |
| S9 | SearchPolicyGenome、Policy Archive、L0 自动调参、CLI status/export/audit | 5–7d |

**Phase 3 验收**：

```text
- 健康指标绑定 SearchPolicyVersion 和时间窗口
- Champion Policy 可完整导出与回滚
- L0 自适应不修改 Task Evaluator 语义
- 路由能分别统计 Director/Coder/Critic 的收益
```

### Phase 4：真正的受控元进化（后续版本）

```text
- Prompt Challenger + Replay / Canary
- PolicyExperiment 等预算比较
- L1 搜索控制器修改
- 评估基础设施非语义适配
- 可选 Bayesian / Advisor 学习
- 可选 Agent 代码自修改，但必须经过同一治理流程
```

首版明确暂缓：

```text
- 无边界 Harness 自重写
- 自动修改评分公式和测试集
- 大规模跨任务全局记忆
- 默认依赖 Neo4j / Milvus / 分布式服务
- 一次覆盖所有语言和硬件环境
```

---

## 十五、v0.2 相对 v0.1 的增量变更摘要

本节只用于说明修订范围，不改变前述设计：

1. 将定位从“零外部服务依赖、pip install 即用”修正为 Local-first、无强制数据库服务、分档安装；
2. 保留四层目录，但新增 Artifact Store、Outbox、Job Lease、Sandbox Backend 和 Policy Evolution 模块；
3. 将 `evo_node` 拆分为 Candidate、Artifact、Lineage、EvaluationRun 和 SearchState；
4. 删除节点级 `health_score`，改为绑定 `SearchPolicyVersion` 的 `MetaEvaluationWindow`；
5. 将单一 `parent_id` 改为多父代 `candidate_lineage`，并区分 Reference Edge；
6. 为 Experiment、Task、Domain、Evaluator、Environment、Embedding 和 Policy 补齐作用域与版本；
7. 将大段代码和运行输出移入 SHA-256 内容寻址 Artifact Store；
8. 通过 SQLite Outbox 解决 SQLite 与 zvec 无法原子双写的问题；
9. 将 zvec 封装为 Adapter，并让 Embedding 维度和模型绑定 Profile；
10. 将单 cosine 新颖性拒绝升级为 Embedding、AST、行为和可选 LLM 的多级门；
11. 解决 TaskEvaluator 与 Sandbox 双重执行冲突，改为 `build_plan()` / `parse_result()`；
12. 默认使用 DockerBackend，Trusted subprocess 仅显式开启；
13. 将 Harness Self-Rewriting 改为受治理的 Evaluation Infrastructure Adaptation；
14. 明确 Task semantics、测试集、评分公式和隐藏数据不可被 Meta-Agent 修改；
15. 将 SelfEvaluator 内部拆为 TelemetryAggregator、HealthPolicy 和 MetaPlanner；
16. 对 ROI、覆盖率、记忆有效性和上下文污染给出可计算定义；
17. 将 SearchPolicyGenome、Champion、Challenger、Replay/Canary 和 Rollback 设为元进化主线；
18. 将固定“前重后轻”UCB1 改为角色条件化的非平稳 Bandit；
19. 增加 L0/L1/L2 元进化风险等级；
20. 保留 S1—S9 名称，但重排依赖、扩大验收标准，并把高风险自修改推迟到 Phase 4。

---

> **本文档为 v0.1 的增量收敛版本。下一步进入阶段 3 时，应以 Phase 1 的数据模型、Artifact、Sandbox 和 Evaluator 边界为先，不应先写 Meta-Agent 或完整 MCTS。**
