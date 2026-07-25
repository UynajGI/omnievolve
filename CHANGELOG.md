# Changelog

## [Unreleased] — 2026-07-22

### 14 项不成熟点修复
- **MCTS 线程安全**: `_last_select_path` 改为 `threading.local()`，消除并行 prepare 竞态
- **异常吞噬修复**: 30 处 `except: pass` 按三级分类补充 logger.debug/warning
- **AsyncEvolutionEngine 废弃护栏**: run() 入口追加 DeprecationWarning + 迁移指南
- **魔术数字提取**: `leakage_score_threshold`/`leakage_penalty_factor` 加入 EvolutionConfig
- **ruff lint**: 16 个错误全部修复（0 errors）
- **测试补全**: 新增 7 个测试文件（prompt_evolver/graph_store_write/vector_indexer/headless_provider/monty_unit/async_pipeline/repository_crud），796 tests passed
- **VectorStore.check_novelty**: 补充设计文档 §8 要求的 Facade 方法
- **不修**: `engine/scheduler.py` 设计文档要求但功能已完全吸收进 evolution_engine.py 主循环，拆分无增益且引入循环依赖风险，决定不修

### 异步流水线引擎
- **AsyncDatabase** (`storage/async_db.py`): asyncio.to_thread + Semaphore(1) 写串行化，WAL 并发读
- **prepare/commit 拆分**: FastLoopStep.evolve_one 拆为 prepare()（无状态变更）+ commit_result()（串行状态更新）
- **AsyncPipelineEngine** (`engine/async_engine.py`): Phase A (parallel prepare) → Phase B (sequential commit) → Phase C (post-gen sync)，EWMA 自适应并发
- **Feature flag**: `async_pipeline_enabled: bool = False` 默认关闭，CLI 自动路由

### 设计文档合规性修复 (G2/G3/G4)
- **GraphStore**: 新增 `add_candidate()` / `add_reference_edge()` / `update_search_state()` 写方法
- **VectorStore facade**: 新增 `semantic_candidates()` / `find_diverse_high_scorers()` / `rag_retrieve()`
- **Plugin enrichment**: `_apply_eval_result()` 中调用 `Plugin.enrich_evaluation()` 补充领域指标

### zvec 0.6 适配器重写
- 对齐 zvec 0.6 真实 API: `create_and_open(path, schema)` + `Collection.upsert/query/delete`
- 修复 cosine metric 距离→相似度转换 (similarity = 1.0 - distance)
- 安装 zvec==0.6.0，HNSW ANN 全链路验证通过

### 测试
- **735 tests**, 5 skipped, 0 failures

## [Unreleased] — 2026-07-21

### P0-1: 评估失败反馈闭环
- **AgentContext.last_eval_failure**: Evaluator stderr + failure_reason 回流到 Coder Prompt
- **InspirationCollector.load_parents()**: 返回三元组 (codes, thoughts, failures)，批量加载父代评估失败信息
- **Coder._build_user_message()**: 注入 `## Previous Evaluation Failure` 区块 + "fix root cause" 指令
- **效果**: sort 5-gen 通过率 19% → 57% (3x)，gen 2+ 不再全部归零

### E2E 测试 bug 修复
- `evaluator.py`: `"python"` → `sys.executable`（系统无 python 二进制）
- `evaluator.py`: 添加 MountSpec 挂载 test_sort.py/benchmark.py
- `subprocess_backend.py`: 实现 `plan.mounts` 拷贝逻辑

### 新增
- `configs/sort_optimization.toml`: 排序优化专用配置（慢循环 enabled）
- `.archive/reports/optimization_plan_v0.3.md`: v0.3 优化计划（P0/P1/P2 全部完成）
- `docs/architecture/`: 4 张交互式 HTML 架构图（archify）
- 10 个新测试 (`tests/agents/test_eval_feedback.py`)，总计 849 tests

## [0.2.0-beta] — 2026-07-20

### 架构
- Fast Loop 11 步管线 + Slow Loop 策略窗口进化
- 渐进式 MCGS 搜索（UCT → Elite 衰减）
- 岛屿模型（多精英档案 + 周期迁移）
- 分层记忆 L0-L4 + 多级新颖性门
- 双轨评估（任务评估器 + 系统健康度）

### 韧性（P0/P1）
- **熔断器**: 3 态断路器（CLOSED→OPEN→HALF_OPEN），防 API 故障失控
- **速率限制器**: 令牌桶控制 API 调用频率
- **检查点恢复**: 每代自动持久化到 DB，崩溃后 resume
- **SQLite WAL**: 并发读写压力测试通过（4 线程）
- **Docker 硬化**: 多阶段构建 + HEALTHCHECK + 禁网/降权/资源限制

### 沙箱
- TrustedSubprocessBackend（本地，默认）
- DockerBackend（禁网、只读、cap_drop、非 root）
- MontyBackend（Rust 沙箱，微秒级启动）
- HardenedBackend（gVisor/nsjail/Firecracker adapter）

### 论文吸收
- **AlphaEvolve**: SEARCH/REPLACE diff + EVOLVE-BLOCK + Rich Prompt + PromptEvolver
- **MLEvolve**: Reference edges + Progressive exploration schedule
- **ShinkaEvolve**: Power law/weighted 采样 + Bandit relative reward

### 可观测性（P2）
- TelemetryAggregator + HealthPolicy + Prometheus export
- OpenTelemetry 集成（可选，零依赖降级）
- 预定义指标（候选/评估/健康度/检查点）

### 测试
- **649 tests**, 56 files, ruff clean, mypy 0 errors (87 source files)
- 分层测试：Tier 1 (FakeLLM, CI) / Tier 2 (真实 LLM 烟雾) / Tier 3 (手动)
- Soak 50 代稳定性验证
- Docker 配置构建全覆盖
- SQLite 并发压力测试

### 运维
- Makefile（分层测试 + lint + type-check）
- PRODUCTION.md 部署清单
- migration CLI（v001→v002 自动迁移）
- .dockerignore + requirements-sandbox.txt
