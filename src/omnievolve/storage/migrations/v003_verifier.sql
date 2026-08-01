-- v003: Probabilistic LLM-as-a-Verifier 持久化
-- 集成计划 §8：verification_batch（每次 parent-pair 或 island-PPT 操作一条）
-- 与 verification_comparison（每个候选对一条）。
-- 原始 prompt、规范化 token distribution 与响应摘要进入 ArtifactStore，
-- 数据库只保存 hash 和摘要。

-- ═══════════════════════════════════════════
-- 验证批次：每次 parent-pair 或 island-PPT 操作一条
-- ═══════════════════════════════════════════
CREATE TABLE IF NOT EXISTS verification_batch (
    id                  TEXT PRIMARY KEY,
    experiment_id       TEXT NOT NULL REFERENCES experiment(id),
    generation          INTEGER,
    island_id           TEXT,
    mode                TEXT NOT NULL,              -- observer/parent_pair/island_ppt
    model               TEXT NOT NULL,
    prompt_version_id   TEXT,
    granularity         INTEGER NOT NULL,
    repetitions         INTEGER NOT NULL,
    criteria_json       TEXT NOT NULL,              -- JSON array
    order_seed          INTEGER NOT NULL,
    capability_hash     TEXT,
    status              TEXT NOT NULL DEFAULT 'completed',
    failure_category    TEXT,
    total_tokens        INTEGER DEFAULT 0,
    cost_usd            REAL,
    cost_known          INTEGER DEFAULT 1,
    started_at          TEXT,
    finished_at         TEXT
);

CREATE INDEX IF NOT EXISTS idx_verification_batch_scope
    ON verification_batch(experiment_id, generation, island_id);

-- ═══════════════════════════════════════════
-- 验证比较：每个候选对一条
-- ═══════════════════════════════════════════
CREATE TABLE IF NOT EXISTS verification_comparison (
    id                  TEXT PRIMARY KEY,
    batch_id            TEXT NOT NULL REFERENCES verification_batch(id),
    left_candidate_id   TEXT NOT NULL REFERENCES candidate(id),
    right_candidate_id  TEXT NOT NULL REFERENCES candidate(id),
    left_score          REAL,
    right_score         REAL,
    preference_left     REAL,
    variance            REAL,
    entropy             REAL,
    probability_coverage REAL,
    criterion_scores_json TEXT,                     -- JSON
    request_hash        TEXT,
    evidence_hash       TEXT REFERENCES artifact(hash),
    attempt             INTEGER DEFAULT 1,
    status              TEXT NOT NULL DEFAULT 'completed'
);

CREATE INDEX IF NOT EXISTS idx_verification_comparison_pair
    ON verification_comparison(left_candidate_id, right_candidate_id);
CREATE INDEX IF NOT EXISTS idx_verification_comparison_batch
    ON verification_comparison(batch_id, status);
