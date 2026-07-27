# OmniEvolve — Agent Guide

> 受控元进化框架 (Controlled Meta-Evolution Framework). LLM-driven code optimization with MCTS search, hierarchical memory, multi-stage novelty gates, and controlled meta-evolution.

## Quick commands

```bash
# Test — 分层策略（见 feedback/layered-llm-testing）
make test                  # Tier 1: 快速单元测试（FakeLLM，CI 默认）
make test-cov              # Tier 1 + 覆盖率
make test-llm              # Tier 2: LLM 烟雾测试（2-3代真实进化，需 API key）
make test-slow             # 慢速/集成测试（Docker, soak）
make test-all              # 全量（不含 LLM）

# 等效 pytest 命令
.venv/bin/python -m pytest -q -m "not slow and not llm"   # 849 tests
.venv/bin/python -m pytest --cov=omnievolve --cov-report=term  # with coverage
.venv/bin/python -m pytest tests/test_p0_quality_gates.py  # P0 gates only

# Lint / type
make lint                  # ruff check
make type-check            # mypy
.venv/bin/ruff check src/omnievolve/ tests/
.venv/bin/python -m mypy src/omnievolve/ --ignore-missing-imports

# Run
.venv/bin/python -m omnievolve.cli run <task.py> -e <module:Class> -c omnievolve.toml --trusted --gens 10
.venv/bin/python -m omnievolve.cli doctor        # env check

# Docker sandbox
docker build -t omnievolve/sandbox:latest .      # build sandbox image
.venv/bin/python -m omnievolve.cli run <task.py> -e <eval> -c omnievolve.toml --gens 30  # with Docker
```

Python 3.12+. Virtualenv at `.venv/`. Config example at `configs/omnievolve.toml.example`.

## Directory layout

```
src/omnievolve/
  engine/     EvolutionEngine (797行,编排), FastLoopStep (prepare/commit), AsyncPipelineEngine, SlowLoopController, InspirationCollector, CheckpointManager, EngineSetup, MCTS, selection, mutation, crossover, novelty, memory, island, scheduler, diff
  agents/     Director, Coder, Critic, LLMGateway (+CircuitBreaker+RateLimiter), ModelRouter, ContextBuilder
  eval/       TaskEvaluator (Protocol), EvaluatorRegistry, EvaluationRun, Telemetry, HealthPolicy, Metrics
  meta/       PolicyGenome, PolicyArchive, Governance (L0/L1/L2), BayesianTuner (GP+EI), InfraAdapter, AuditReport, PromptEvolver
  sandbox/    TrustedSubprocessBackend（默认，本地）, DockerBackend, MontyBackend, HardenedBackend (Protocol: SandboxBackend)
  storage/    SQLite DB, AsyncDatabase, ArtifactStore (SHA-256 CAS), GraphStore, VectorStore, HybridRetriever, ZvecBackend (HNSW), JobStore, UnitOfWork
  plugins/    BasePlugin, QuantPlugin, GeoPlugin, PluginDiscovery (namespace autoload)
  utils/      Embedding (SentenceTransformerEmbedder + LiteLLMEmbedder + FakeEmbedder, create_embedder factory, HF→hf-mirror→ModelScope auto-fallback), TokenCounter, SeedManager, ConfigSnapshot, Hashing, Profiling (PipelineProfiler + StepTimer + @profile_step)
  cli.py      Typer CLI (run/status/best/export/policy/audit/recover/migrate/doctor)
  config.py   OmniEvolveSettings (pydantic-settings)
  exceptions.py  类型化异常层次 (OmniEvolveError → Sandbox/LLM/Evolution/…)
docs/         User-facing docs (health_metrics, evaluator_guide, prompt_agent_guide, storage_adr, etc.)
docs/architecture/  Interactive HTML architecture diagrams (system-overview, fast-loop, slow-loop, storage)
examples/     python_optimization + circle_packing + heilbronn + matmul demo projects
tests/        849 tests (pytest markers: unit/integration/llm/llm_smoke/slow/e2e/benchmark)
uv.lock       Deterministic dependency lock (163 packages)
Dockerfile    Sandbox image (python:3.12-slim, non-root user)
.github/      CI (ruff + mypy + pytest --cov + docker + integration, 3.12+3.13 matrix)
scripts/      profile_pipeline.py (Scalene 行级性能分析入口)
```

## Design red-lines (do not cross)

- **MCTS tree-edge search only.** All exploration moves (parameter/orchestration/component/paradigm) are tree edges — never greedy/sequential "converge then swap". Combinations can produce 1+1>2 effects; UCT + Beta backpropagation handles this.
- **Evaluator semantic immutability (L2).** Task semantics, correctness tests, hidden data, metric definitions, score formulas are permanently forbidden from auto-modification. See `meta/governance.py` GovernancePolicy.
- **Sandbox default-deny.** DockerBackend defaults: network=none, read-only root, run-as-non-root, drop capabilities, no-new-privileges. `--trusted` flag bypasses for dev only.
- **Artifact content-addressed.** All code stored via ArtifactStore with SHA-256 hashing. Never write candidate code to ad-hoc paths.
- **Vector outbox consistency.** Candidate/thought creation must enqueue `vector_index_job` entries — the embedding/novelty/memory pipeline depends on it.
- **EvaluationRun idempotent.** Same (candidate, evaluator_version, environment_version, seed, split, attempt) must not create duplicate rows.

## Key architecture decisions

- **Fast Loop** (11 steps per candidate): Router → MCTS parent selection → crossover/mutation → Director → NoveltyGate → Coder → Critic retry → ArtifactStore → TaskEvaluator → Sandbox → state update. **P0-1**: Evaluator stderr/failure_reason flows back to Coder via `AgentContext.last_eval_failure` (pass rate 19%→57%).
- **Slow Loop** (every `health_window_gens`): TelemetryAggregator → HealthPolicy → MetaPlanner → Governance L0/L1/L2 → Challenger policy → Replay comparison → promote/reject
- **Protocols are duck-typed** (`@runtime_checkable`): TaskEvaluator, SandboxBackend, VectorBackend, Repository, Embedder, Plugin, DirectorAgent, CoderAgent, CriticAgent. Concrete classes use different names (e.g. `Director` implements `DirectorAgent`).
- **`docs/project-design/`** has been archived to `.archive/` (not git-tracked). The frozen spec lives at `.archive/project-design/reference/OmniEvolve_v0.2_设计文档.md`.

## Deep-dive docs

| Topic | Doc |
|-------|-----|
| Architecture overview & CLI usage | `README.md` |
| Health metrics formulas & limitations | `docs/health_metrics.md` |
| Agent development (prompts, context, retry) | `docs/prompt_agent_guide.md` |
| Evaluator development guide | `docs/evaluator_guide.md` |
| Storage ADR & operations | `docs/storage_adr.md` |
| Docker security baseline | `docs/docker_security_baseline.md` |
| Vector config & migration | `docs/vector_configuration.md` |
| Architecture diagrams (interactive) | `docs/architecture/` (4 HTML files) |
| Release notes (features, known limits) | `docs/release_notes_v0.2.md` |
| Source audit (dead code + bugs) | `.archive/reports/dead_code_and_bug_findings.md` |
