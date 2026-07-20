# OmniEvolve — Agent Guide

> 受控元进化框架 (Controlled Meta-Evolution Framework). LLM-driven code optimization with MCTS search, hierarchical memory, multi-stage novelty gates, and controlled meta-evolution.

## Quick commands

```bash
# Test
.venv/bin/python -m pytest -q                    # 211 tests
.venv/bin/python -m pytest -q -m "not slow"      # fast subset
.venv/bin/python -m pytest --cov=omnievolve --cov-report=term  # with coverage
.venv/bin/python -m pytest tests/test_p0_quality_gates.py  # P0 gates only

# Lint / type
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
  engine/     EvolutionEngine, AsyncEngine, MCTS, selection, mutation, crossover, novelty, memory, island, scheduler
  agents/     Director, Coder, Critic, LLMGateway, ModelRouter, ContextBuilder
  eval/       TaskEvaluator (Protocol), EvaluatorRegistry, EvaluationRun, Telemetry, HealthPolicy, Metrics
  meta/       PolicyGenome, PolicyArchive, Governance (L0/L1/L2), InfraAdapter, AuditReport, PromptEvolver
  sandbox/    DockerBackend, TrustedSubprocessBackend, HardenedBackend (Protocol: SandboxBackend)
  storage/    SQLite DB, ArtifactStore (SHA-256 CAS), GraphStore, VectorStore, JobStore, UnitOfWork
  plugins/    BasePlugin, QuantPlugin, GeoPlugin, PluginDiscovery (namespace autoload)
  utils/      Embedding, TokenCounter, SeedManager, ConfigSnapshot, Hashing
  cli.py      Typer CLI (run/status/best/export/policy/audit/recover/doctor)
  config.py   OmniEvolveSettings (pydantic-settings)
  exceptions.py  类型化异常层次 (OmniEvolveError → Sandbox/LLM/Evolution/…)
docs/         User-facing docs (NOT project-design specs)
docs/project-design/  Design specs — DO NOT MODIFY (frozen requirements)
reports/      Phase acceptance + gap analysis reports
examples/     python_optimization + circle_packing demo projects
tests/        211 tests across 17 files (pytest markers: unit/integration/llm/slow/e2e/benchmark)
uv.lock       Deterministic dependency lock (159 packages)
Dockerfile    Sandbox image (python:3.12-slim, non-root user)
.github/      CI (ruff + mypy + pytest --cov + docker + integration, 3.12+3.13 matrix)
```

## Design red-lines (do not cross)

- **MCTS tree-edge search only.** All exploration moves (parameter/orchestration/component/paradigm) are tree edges — never greedy/sequential "converge then swap". Combinations can produce 1+1>2 effects; UCT + Beta backpropagation handles this.
- **Evaluator semantic immutability (L2).** Task semantics, correctness tests, hidden data, metric definitions, score formulas are permanently forbidden from auto-modification. See `meta/governance.py` GovernancePolicy.
- **Sandbox default-deny.** DockerBackend defaults: network=none, read-only root, run-as-non-root, drop capabilities, no-new-privileges. `--trusted` flag bypasses for dev only.
- **Artifact content-addressed.** All code stored via ArtifactStore with SHA-256 hashing. Never write candidate code to ad-hoc paths.
- **Vector outbox consistency.** Candidate/thought creation must enqueue `vector_index_job` entries — the embedding/novelty/memory pipeline depends on it.
- **EvaluationRun idempotent.** Same (candidate, evaluator_version, environment_version, seed, split, attempt) must not create duplicate rows.

## Key architecture decisions

- **Fast Loop** (11 steps per candidate): Router → MCTS parent selection → crossover/mutation → Director → NoveltyGate → Coder → Critic retry → ArtifactStore → TaskEvaluator → Sandbox → state update
- **Slow Loop** (every `health_window_gens`): TelemetryAggregator → HealthPolicy → MetaPlanner → Governance L0/L1/L2 → Challenger policy → Replay comparison → promote/reject
- **Protocols are duck-typed** (`@runtime_checkable`): TaskEvaluator, SandboxBackend, VectorBackend, Repository, Embedder, Plugin, DirectorAgent, CoderAgent, CriticAgent. Concrete classes use different names (e.g. `Director` implements `DirectorAgent`).
- **`docs/project-design/`** is the frozen spec (31 files). Do not modify these — they are the source-of-truth requirements, not editable documentation.

## Deep-dive docs

| Topic | Doc |
|-------|-----|
| Architecture overview & CLI usage | `README.md` |
| Health metrics formulas & limitations | `docs/health_metrics.md` |
| Agent development (prompts, context, retry) | `docs/prompt_agent_guide.md` |
| Release notes (features, known limits) | `docs/release_notes_v0.2.md` |
| Design specification (frozen) | `docs/project-design/reference/OmniEvolve_v0.2_设计文档.md` |
