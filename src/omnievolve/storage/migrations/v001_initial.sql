-- v001_initial.sql — Initial schema for OmniEvolve v0.2
-- S1-03: 迁移文件 — 版本 1

-- 包含完整的初始 schema：18 张表、索引、WAL 配置
-- 后续版本有增量迁移文件 (v002_*.sql, v003_*.sql...)

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;
PRAGMA busy_timeout = 5000;

-- Schema 版本管理
CREATE TABLE IF NOT EXISTS schema_version (
    version             INTEGER PRIMARY KEY,
    applied_at          TEXT DEFAULT (datetime('now')),
    description         TEXT
);

-- 实验
CREATE TABLE IF NOT EXISTS experiment (
    id                  TEXT PRIMARY KEY,
    task_id             TEXT NOT NULL,
    task_name           TEXT NOT NULL,
    domain_id           TEXT,
    status              TEXT NOT NULL DEFAULT 'created',
    config_snapshot     TEXT NOT NULL,
    baseline_candidate_id TEXT,
    champion_policy_id  TEXT,
    started_at          TEXT DEFAULT (datetime('now')),
    finished_at         TEXT,
    total_tokens        INTEGER DEFAULT 0,
    total_cost_usd      REAL DEFAULT 0,
    total_compute_sec   REAL DEFAULT 0
);

-- Artifact
CREATE TABLE IF NOT EXISTS artifact (
    hash                TEXT PRIMARY KEY,
    artifact_type       TEXT NOT NULL,
    byte_size           INTEGER NOT NULL,
    media_type          TEXT,
    relative_path       TEXT NOT NULL,
    base_artifact_hash  TEXT REFERENCES artifact(hash),
    created_at          TEXT DEFAULT (datetime('now')),
    meta                TEXT
);

-- 思想记录
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

-- Candidate
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
    meta                TEXT
);

CREATE INDEX IF NOT EXISTS idx_candidate_exp_gen ON candidate(experiment_id, generation);
CREATE INDEX IF NOT EXISTS idx_candidate_policy ON candidate(search_policy_id);
CREATE INDEX IF NOT EXISTS idx_candidate_status ON candidate(status);

-- 血缘
CREATE TABLE IF NOT EXISTS candidate_lineage (
    child_id            TEXT NOT NULL REFERENCES candidate(id),
    parent_id           TEXT NOT NULL REFERENCES candidate(id),
    relation_type       TEXT NOT NULL,
    parent_order        INTEGER DEFAULT 0,
    op_detail           TEXT,
    created_at          TEXT DEFAULT (datetime('now')),
    PRIMARY KEY(child_id, parent_id, relation_type)
);
CREATE INDEX IF NOT EXISTS idx_lineage_parent ON candidate_lineage(parent_id);

-- 引用边
CREATE TABLE IF NOT EXISTS candidate_reference_edge (
    src_candidate_id    TEXT NOT NULL REFERENCES candidate(id),
    dst_candidate_id    TEXT NOT NULL REFERENCES candidate(id),
    reference_type      TEXT NOT NULL,
    detail              TEXT,
    created_at          TEXT DEFAULT (datetime('now')),
    PRIMARY KEY(src_candidate_id, dst_candidate_id, reference_type)
);

-- 搜索状态
CREATE TABLE IF NOT EXISTS candidate_search_state (
    candidate_id        TEXT PRIMARY KEY REFERENCES candidate(id),
    visit_count         INTEGER DEFAULT 0,
    value_sum           REAL DEFAULT 0,
    prior               REAL DEFAULT 0,
    virtual_loss        REAL DEFAULT 0,
    selection_count     INTEGER DEFAULT 0,
    offspring_count     INTEGER DEFAULT 0,
    frontier_status     TEXT DEFAULT 'open',
    updated_at          TEXT DEFAULT (datetime('now'))
);

-- 评估器版本
CREATE TABLE IF NOT EXISTS task_evaluator_version (
    id                  TEXT PRIMARY KEY,
    name                TEXT NOT NULL,
    semantic_version    TEXT NOT NULL,
    implementation_hash TEXT NOT NULL,
    dataset_hash        TEXT,
    task_semantics_hash TEXT NOT NULL,
    score_schema        TEXT NOT NULL,
    immutable_core      INTEGER NOT NULL DEFAULT 1,
    created_at          TEXT DEFAULT (datetime('now')),
    UNIQUE(name, semantic_version, implementation_hash)
);

-- 执行环境版本
CREATE TABLE IF NOT EXISTS execution_environment_version (
    id                  TEXT PRIMARY KEY,
    backend             TEXT NOT NULL,
    image_digest        TEXT,
    compiler_digest     TEXT,
    dependency_lock_hash TEXT,
    cpu_profile         TEXT,
    resource_policy     TEXT NOT NULL,
    network_policy      TEXT NOT NULL,
    created_at          TEXT DEFAULT (datetime('now'))
);

-- 评估运行
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
    metrics             TEXT,
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
CREATE INDEX IF NOT EXISTS idx_eval_candidate ON evaluation_run(candidate_id);
CREATE INDEX IF NOT EXISTS idx_eval_scope ON evaluation_run(experiment_id, evaluator_version_id, environment_version_id);

-- Search Policy
CREATE TABLE IF NOT EXISTS search_policy_version (
    id                  TEXT PRIMARY KEY,
    experiment_id       TEXT REFERENCES experiment(id),
    parent_policy_id    TEXT REFERENCES search_policy_version(id),
    version             INTEGER NOT NULL,
    genome              TEXT NOT NULL,
    risk_level          TEXT NOT NULL DEFAULT 'L0',
    status              TEXT NOT NULL DEFAULT 'challenger',
    artifact_hash       TEXT REFERENCES artifact(hash),
    created_at          TEXT DEFAULT (datetime('now')),
    UNIQUE(experiment_id, version)
);

CREATE TABLE IF NOT EXISTS policy_experiment (
    id                  TEXT PRIMARY KEY,
    experiment_id       TEXT NOT NULL REFERENCES experiment(id),
    champion_policy_id  TEXT NOT NULL REFERENCES search_policy_version(id),
    challenger_policy_id TEXT NOT NULL REFERENCES search_policy_version(id),
    evaluation_mode     TEXT NOT NULL,
    budget_spec         TEXT NOT NULL,
    replay_snapshot_hash TEXT REFERENCES artifact(hash),
    status              TEXT NOT NULL DEFAULT 'queued',
    promotion_decision  TEXT,
    evidence            TEXT,
    created_at          TEXT DEFAULT (datetime('now')),
    finished_at         TEXT
);

-- Meta 评估窗口
CREATE TABLE IF NOT EXISTS meta_evaluation_window (
    id                  TEXT PRIMARY KEY,
    experiment_id       TEXT NOT NULL REFERENCES experiment(id),
    search_policy_id    TEXT NOT NULL REFERENCES search_policy_version(id),
    generation_start    INTEGER NOT NULL,
    generation_end      INTEGER NOT NULL,
    candidate_count     INTEGER NOT NULL,
    telemetry           TEXT NOT NULL,
    roi_score           REAL,
    coverage_entropy    REAL,
    memory_effectiveness REAL,
    pollution_ratio     REAL,
    alert_level         TEXT DEFAULT 'ok',
    recommendations     TEXT,
    should_trigger_meta INTEGER DEFAULT 0,
    created_at          TEXT DEFAULT (datetime('now'))
);

-- 分层记忆
CREATE TABLE IF NOT EXISTS memory_entry (
    id                  TEXT PRIMARY KEY,
    experiment_id       TEXT REFERENCES experiment(id),
    task_id             TEXT,
    task_family         TEXT,
    domain_id           TEXT,
    branch_id           TEXT,
    scope_level         INTEGER NOT NULL,
    thought_id          TEXT REFERENCES thought_record(id),
    candidate_id        TEXT REFERENCES candidate(id),
    code_diff_hash      TEXT REFERENCES artifact(hash),
    outcome_summary     TEXT NOT NULL,
    success_flag        INTEGER NOT NULL,
    embedding_code_ref  TEXT,
    embedding_thought_ref TEXT,
    created_at          TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_memory_scope ON memory_entry(scope_level, experiment_id, task_id, domain_id);

-- Prompt & Embedding 版本
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
    purpose             TEXT NOT NULL,
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

-- Vector Outbox
CREATE TABLE IF NOT EXISTS vector_index_job (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type         TEXT NOT NULL,
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

-- Job Lease
CREATE TABLE IF NOT EXISTS job (
    id                  TEXT PRIMARY KEY,
    experiment_id       TEXT NOT NULL REFERENCES experiment(id),
    job_type            TEXT NOT NULL,
    payload             TEXT NOT NULL,
    status              TEXT NOT NULL DEFAULT 'queued',
    attempt             INTEGER DEFAULT 0,
    max_attempts        INTEGER DEFAULT 3,
    lease_owner         TEXT,
    lease_expires_at    TEXT,
    heartbeat_at        TEXT,
    result_ref          TEXT,
    last_error          TEXT,
    created_at          TEXT DEFAULT (datetime('now')),
    updated_at          TEXT DEFAULT (datetime('now'))
);

-- LLM Call Ledger
CREATE TABLE IF NOT EXISTS llm_call_ledger (
    id                  TEXT PRIMARY KEY,
    experiment_id       TEXT,
    agent_role          TEXT NOT NULL,
    model               TEXT NOT NULL,
    prompt_version_id   TEXT,
    input_tokens        INTEGER DEFAULT 0,
    output_tokens       INTEGER DEFAULT 0,
    total_tokens        INTEGER DEFAULT 0,
    cost_usd            REAL DEFAULT 0,
    latency_ms          REAL DEFAULT 0,
    request_hash        TEXT,
    response_hash       TEXT,
    created_at          TEXT DEFAULT (datetime('now'))
);
