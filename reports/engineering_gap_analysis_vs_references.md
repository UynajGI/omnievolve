# OmniEvolve vs 5 Reference Projects — Engineering Gap Analysis

> Generated: 2026-07-20 | Comparing OmniEvolve v0.2 against OpenEvolve, ShinkaEvolve, EvoX, DGM, MLEvolve

---

## Dimension-by-Dimension Comparison Matrix

### 1. CI/CD Quality Gates

| Feature | OmniEvolve | OpenEvolve | ShinkaEvolve | EvoX | DGM | MLEvolve |
|---------|-----------|------------|-------------|------|-----|----------|
| Matrix builds | ✅ 3.12, 3.13 | ❌ Single 3.10 | ❌ Single 3.11 | ✅ 3.10-3.13 | ❌ None | ❌ None |
| Coverage upload | ✅ XML artifact | ❌ None | ✅ XML artifact | ❌ None | ❌ None | ❌ None |
| Coverage threshold | ❌ No fail-under | ❌ None | ❌ None | ❌ None | ❌ None | ❌ None |
| Benchmark CI | ✅ Separate workflow | ❌ None | ❌ None | ❌ None | ❌ None | ❌ None |
| Docker CI | ✅ Build+verify | ❌ None | ❌ None | ❌ None | ❌ None | ❌ None |
| PyPI publish | ✅ Trusted (OIDC) | ✅ Trusted (OIDC) | ✅ Trusted (OIDC) | ✅ Trusted (OIDC) | ❌ None | ❌ None |
| Security scan | ❌ None | ✅ Frame SAST | ❌ None | ❌ None | ❌ None | ❌ None |
| Code review bot | ✅ Claude Code | ✅ Claude Code | ✅ Claude Code | ❌ None | ❌ None | ❌ None |
| Integration tests | ✅ slow+e2e | ✅ Real LLM | ✅ requires_secrets | ❌ None | ❌ None | ❌ None |

**OmniEvolve gap**: Add `--cov-fail-under=80` to CI. Add security scanning (bandit or similar).

---

### 2. Testing Patterns

| Feature | OmniEvolve | OpenEvolve | ShinkaEvolve | EvoX | DGM | MLEvolve |
|---------|-----------|------------|-------------|------|-----|----------|
| Test framework | pytest | unittest | pytest | unittest | pytest | ❌ None |
| Test count | 211 (17 files) | ~450 (58 files) | 65 files | 32 files | 2 test files | 0 |
| Property-based | ✅ Hypothesis | ❌ | ❌ | ❌ | ❌ | ❌ |
| Benchmark tests | ✅ perf_counter | ❌ | ❌ | ❌ | ❌ | ❌ |
| Benchmark regression | ❌ No compare | ❌ | ❌ | ❌ | ❌ | ❌ |
| conftest fixtures | ✅ 4 + FakeLLM | ❌ None | ❌ Minimal | ❌ None | ❌ Minimal | ❌ None |
| Strict markers | ✅ Yes | ✅ Yes | ✅ Yes | ❌ None | ❌ None | ❌ None |

**OmniEvolve unique strength**: Only project with Hypothesis property-based tests and benchmark tests.
**OmniEvolve gap**: No benchmark regression detection (compare against stored baseline). OpenEvolve has ~2x test coverage by volume.

---

### 3. Async/Parallel Execution

| Feature | OmniEvolve | OpenEvolve | ShinkaEvolve | EvoX | DGM | MLEvolve |
|---------|-----------|------------|-------------|------|-----|----------|
| ThreadPoolExecutor | ✅ async_engine.py | ❌ | ✅ Dual pools | ❌ | ✅ 6 locations | ✅ run.py |
| ProcessPoolExecutor | ❌ | ✅ process_parallel.py | ❌ | ❌ | ❌ (imported unused) | ❌ |
| asyncio | ✅ Event+Semaphore+Tasks | ✅ run+TaskPool | ✅ Full async arch | ❌ | ✅ bash tool only | ❌ |
| asyncio.Semaphore rate limit | ✅ Semaphore(concurrency) | ✅ Semaphore in TaskPool | ✅ Semaphore(8) for DB | ❌ | ❌ | ❌ |
| Deadlock monitor | ❌ | ❌ | ✅ 10s interval | ❌ | ❌ | ❌ |
| Distributed | ✅ SQLite lease-based | ❌ | ❌ | ✅ torch.distributed | ❌ | ❌ |
| GPU parallelism | ❌ | ❌ | ❌ | ✅ vmap+triton | ❌ | ❌ |
| Signal handling | ✅ SIGINT/SIGTERM async | ❌ | ❌ | ❌ | ❌ | ✅ SIGINT→SIGKILL |

**OmniEvolve gap**: ShinkaEvolve's deadlock monitor (`async_dbase.py:170-188`) is a pattern to adopt for DB operations. OpenEvolve's ProcessPoolExecutor pattern for CPU-bound evaluation isolation is worth considering.

---

### 4. Error Handling

| Feature | OmniEvolve | OpenEvolve | ShinkaEvolve | EvoX | DGM | MLEvolve |
|---------|-----------|------------|-------------|------|-----|----------|
| Typed exceptions | ✅ 10 classes | ❌ None | ❌ 1 class | ❌ None | ❌ None | ❌ None |
| Retry decorator | ❌ Hand-rolled | ❌ Hand-rolled | ✅ db_retry decorator | ❌ None | ✅ @backoff.on_exception | ❌ Hand-rolled |
| Retry library | ❌ None | ❌ None | ❌ None | ❌ None | ✅ backoff lib | ❌ tenacity unused |
| Circuit breaker | ❌ None | ❌ None | ❌ None | ❌ None | ❌ None | ❌ None |
| Backoff constants | ❌ Inline magic numbers | ❌ Inline | ✅ env-tuned module | ❌ None | ❌ Inline | ✅ backoff lib |
| Exception usage | ❌ 1/30 blocks use typed | N/A | N/A | N/A | N/A | N/A |

**OmniEvolve critical gap**: 10-typed exception hierarchy exists but only ONE `except SandboxError` uses it. Remaining 30+ blocks use bare `except Exception`. Adopt `stamina` or `tenacity` library for retry (replace hand-rolled loops in `llm_gateway.py`, `context_builder.py`, `evolution_engine.py`).

**ShinkaEvolve pattern to adopt**: `db_retry` decorator with exponential backoff (`shinka/database/dbase.py:107-143`) applied to 13 database methods. And env-tuned LLM backoff constants in `shinka/llm/constants.py`.

---

### 5. Config Management

| Feature | OmniEvolve | OpenEvolve | ShinkaEvolve | EvoX | DGM | MLEvolve |
|---------|-----------|------------|-------------|------|-----|----------|
| Framework | pydantic-settings | dataclass+dacite | Hydra+OmegaConf | Code-as-config | argparse only | OmegaConf+dataclass |
| Config format | TOML | YAML | YAML (Hydra) | None | CLI args | YAML |
| Config groups | ❌ Flat | ❌ Flat | ✅ 5 groups | ❌ None | ❌ None | ❌ Flat YAML |
| CLI overrides | ✅ env+TOML→CLI | ✅ `${VAR}` | ✅ Hydra CLI | ❌ None | ✅ argparse | ✅ OmegaConf.from_cli |
| Schema validation | ✅ pydantic v2 | ❌ dacite only | ✅ OmegaConf.structured | ❌ None | ❌ None | ✅ OmegaConf.structured |
| Secret masking | ✅ config_snapshot.py | ❌ None | ❌ None | ❌ None | ❌ None | ❌ None |
| Reproducibility | ❌ No config snapshot | ❌ None | ✅ saves .hydra/ YAML | ❌ None | ❌ None | ❌ auto coolname slug |

**OmniEvolve gap**: ShinkaEvolve's Hydra config group composition (database/island_medium + evolution/medium_budget + task/circle_packing) enables cleaner experiment variants. OmniEvolve's flat TOML requires duplicating configs. Also missing config snapshot for reproducibility (ShinkaEvolve saves `hydra.yaml` + `overrides.yaml` per run).

---

### 6. Logging/Observability

| Feature | OmniEvolve | OpenEvolve | ShinkaEvolve | EvoX | DGM | MLEvolve |
|---------|-----------|------------|-------------|------|-----|----------|
| Structured logging | ⚠️ Code exists, not wired | ❌ stdlib only | ❌ stdlib only | ❌ None | ❌ stdlib only | ❌ stdlib+Rich |
| JSON format | ⚠️ StructuredFormatter defined | ❌ | ❌ | ❌ | ❌ | ❌ |
| structlog | ⚠️ setup_structlog() defined | ❌ | ❌ | ❌ | ❌ | ❌ |
| W&B / experiment tracking | ❌ | ❌ | ✅ W&B optional | ❌ | ❌ | ❌ wandb unused |
| Prometheus metrics | ⚠️ String builder, no HTTP | ❌ | ❌ | ❌ | ❌ | ❌ |
| OpenTelemetry | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Telemetry pipeline | ✅ HealthMetrics+Policy | ❌ | ❌ | ❌ | ❌ | ❌ |
| Budget tracking | ✅ TokenCounter+BudgetGuard | ❌ | ❌ | ❌ | ❌ | ❌ |
| Rich progress | ✅ Rich via typer | ✅ tqdm | ❌ | ❌ | ❌ | ✅ Rich Status+Tree |

**OmniEvolve critical gap**: `StructuredFormatter` (JSON), `setup_structlog()`, `ProvenanceLogger` are all defined in `utils/logging.py` but NEVER called. Wiring them in is a one-line change. ShinkaEvolve's W&B integration (`shinka/wandb_logging.py`) tracks generation, score, cost breakdown — adopt this pattern. Prometheus exporter needs HTTP endpoint.

---

### 7. Dependency Management

| Feature | OmniEvolve | OpenEvolve | ShinkaEvolve | EvoX | DGM | MLEvolve |
|---------|-----------|------------|-------------|------|-----|----------|
| Lock file | ✅ uv.lock (159 pkgs) | ❌ None | ❌ None | ❌ None | ❌ None | ❌ None |
| Build backend | hatchling | setuptools | ? | setuptools | ❌ None | ❌ None |
| Optional extras | ✅ 5 groups | ❌ Flat | ✅ wandb extra | ✅ 5 groups | ❌ Flat | ❌ 3 flat files |
| Version pins | ✅ Deterministic lock | ❌ Loose | ❌ Only 2 pinned | ❌ Lower bounds | ❌ Unpinned | ❌ Loose |
| Dependabot/Renovate | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |

**OmniEvolve unique strength**: Only project with deterministic lock file. **Gap**: Add Dependabot or Renovate for automated dependency updates.

---

### 8. Code Quality

| Feature | OmniEvolve | OpenEvolve | ShinkaEvolve | EvoX | DGM | MLEvolve |
|---------|-----------|------------|-------------|------|-----|----------|
| Linter | ✅ Ruff (E,F,I,N,W,UP) | ❌ None | ⚠️ Ruff tests only | ✅ Ruff (F,E,W,I,NPY) | ❌ None | ❌ None |
| Formatter | ✅ Ruff format | ✅ black+isort | ✅ black+isort | ✅ Ruff format | ❌ None | ⚠️ Black as lib |
| Type checker | ✅ mypy CLI | ✅ mypy strict | ⚠️ mypy tests only | ❌ None | ❌ None | ❌ None |
| Type checker config | ❌ No [tool.mypy] | ❌ No file | ❌ No file | ❌ None | ❌ None | ❌ None |
| Pre-commit hooks | ✅ lefthook | ✅ .pre-commit | ❌ None | ✅ .pre-commit | ❌ installed, unused | ❌ None |
| Pre-push tests | ✅ lefthook | ❌ | ❌ | ❌ | ❌ | ❌ |

**OmniEvolve gap**: Add `[tool.mypy]` config with `strict = true` (OpenEvolve's mypy settings are stricter). Also add `pytest --benchmark-compare` to CI benchmark workflow for regression detection.

---

### 9. Plugin/Extension System

| Feature | OmniEvolve | OpenEvolve | ShinkaEvolve | EvoX | DGM | MLEvolve |
|---------|-----------|------------|-------------|------|-----|----------|
| Plugin Protocol | ✅ Plugin Protocol | ❌ | ✅ ABC strategy | ❌ | ❌ | ❌ |
| Auto-discovery | ✅ pkgutil scan | ❌ | ❌ Hydra instantiate | ✅ pkgutil namespace | ⚠️ glob tools/*.py | ❌ |
| Namespace package | ❌ Not configured | ❌ | ❌ | ✅ evox_ext (PEP 420) | ❌ | ❌ |
| Entry points | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Wired into engine | ❌ Dead code | ❌ | ✅ Via Hydra config | ✅ at import evox | ✅ at import | ❌ |
| Extensions shipped | 2 (quant, geo) | Provider registry | Bandit strategies | evox_ext.algorithms | 2 tools | Hardcoded agents |

**OmniEvolve critical gap**: Plugin discovery is defined but NEVER called by the engine or CLI. EvoX's pattern (`src/evox/__init__.py:26-27`) calls `auto_load_extensions()` at import time — simple and effective. OmniEvolve should call `discover_plugins()` in engine initialization.

**EvoX pattern to follow**: PEP 420 namespace `evox_ext` with `pkgutil.iter_modules()` auto-discovery, setattr onto target module, update `__all__`. `src/evox_ext/autoload_ext.py:1-98`.

---

### 10. Documentation

| Feature | OmniEvolve | OpenEvolve | ShinkaEvolve | EvoX | DGM | MLEvolve |
|---------|-----------|------------|-------------|------|-----|----------|
| API docs | ❌ None | ❌ None | ✅ mkdocstrings | ✅ Sphinx autodoc2 | ❌ None | ❌ None |
| Doc builder | ❌ None | ❌ None | ✅ mkdocs-material | ✅ Sphinx+shibuya | ❌ None | ❌ None |
| Tutorials | ❌ None | ✅ 35 examples | ✅ 7-part tutorial | ✅ 7 tutorials + 7 notebooks | ❌ None | ❌ None |
| Design specs | ✅ 31 frozen docs | ❌ | ❌ | ❌ | ❌ | ❌ |
| Compliance audit | ✅ gap+checklist+compliance | ❌ | ❌ | ❌ | ❌ | ❌ |
| Bilingual | ❌ | ❌ | ❌ | ✅ EN+中文 | ❌ | ❌ |
| Architecture diagrams | ❌ In README text | ✅ PNG diagram | ❌ | ❌ | ❌ | ❌ |
| CHANGELOG | ❌ | ❌ | ✅ CHANGELOG.md | ❌ | ❌ | ❌ |
| CONTRIBUTING | ❌ | ✅ | ✅ | ❌ | ❌ | ❌ |
| LICENSE file | ❌ (README claims MIT) | ✅ | ✅ | ✅ | ✅ | ✅ |

**OmniEvolve gap**: No API documentation infrastructure. ShinkaEvolve's mkdocs-material + mkdocstrings pattern (`mkdocs.yml` + `docs/reference/`) is the quickest path to generated API docs. Also missing LICENSE file, CONTRIBUTING.md, CHANGELOG.md.

---

## Ranked Priority List (Most Impactful Gaps First)

### 🔴 P0 — Fix Dead Code (existing code that should work but doesn't)

| # | Gap | Current State | Fix | Reference Pattern |
|---|-----|--------------|-----|-------------------|
| 1 | **Structured logging not wired** | `utils/logging.py` has `StructuredFormatter`, `setup_structlog()`, `ProvenanceLogger` — never called | Call `setup_logging()` at engine start | — |
| 2 | **Plugin system not wired** | `plugins/discovery.py` `discover_plugins()` only called in tests | Call in `EvolutionEngine.__init__` or `cli.py` | EvoX: `auto_load_extensions()` at `import evox` time |
| 3 | **Typed exceptions not used** | 10-class hierarchy, only 1 `except SandboxError` | Replace bare `except Exception` with typed catches | — |

### 🟡 P1 — High-Impact Improvements

| # | Gap | Current State | Fix | Reference Pattern |
|---|-----|--------------|-----|-------------------|
| 4 | **Retry library adoption** | Hand-rolled retry in 3 files (llm_gateway, context_builder, evolution_engine) | Adopt `stamina` or `tenacity` with declarative decorators | DGM: `@backoff.on_exception(backoff.expo, ...)` in `llm.py:88` |
| 5 | **W&B experiment tracking** | No experiment tracking UI | Add optional W&B integration like ShinkaEvolve | ShinkaEvolve: `shinka/wandb_logging.py` — tracks gen/score/cost |
| 6 | **API documentation** | Zero generated API docs | Add mkdocs-material + mkdocstrings | ShinkaEvolve: `mkdocs.yml` + `docs/reference/` |
| 7 | **Coverage threshold** | No `--cov-fail-under` | Add `--cov-fail-under=75` to CI | — |
| 8 | **Mypy strict config** | No `[tool.mypy]` | Add `strict = true` like OpenEvolve | OpenEvolve: `disallow_untyped_defs=true` etc. |
| 9 | **Use typed exceptions throughout** | 30+ bare `except Exception` | Replace with specific `except LLMError`, `except StorageError`, etc. | — |

### 🟢 P2 — Nice-to-Have

| # | Gap | Current State | Fix | Reference Pattern |
|---|-----|--------------|-----|-------------------|
| 10 | **Benchmark regression** | CI runs benchmarks but doesn't compare | Add `pytest-benchmark compare` against stored baseline | — |
| 11 | **Config groups** | Flat TOML config | Consider Hydra config groups for task/evolution/database composition | ShinkaEvolve: 5 config groups in `shinka/configs/` |
| 12 | **Deadlock monitor** | No DB deadlock detection | Add background deadlock monitor task | ShinkaEvolve: `async_dbase.py:170-188` 10s interval |
| 13 | **Security scanning** | No SAST in CI | Add bandit or similar | OpenEvolve: Frame SAST in `.github/workflows/security-scan.yml` |
| 14 | **Dependabot/Renovate** | No automated dep updates | Add Renovate config | — |
| 15 | **Config reproducibility** | No per-run config snapshot | Save resolved config + overrides per run | ShinkaEvolve: `OmegaConf.save(cfg, hydra_dir / "config.yaml")` |
| 16 | **LICENSE / CONTRIBUTING / CHANGELOG** | Missing | Add standard community files | ShinkaEvolve has all three |
| 17 | **LLM backoff constants** | Magic numbers inline | Extract to env-tuned constants module | ShinkaEvolve: `shinka/llm/constants.py` |
| 18 | **ProcessPool for CPU eval** | Only ThreadPool | Consider ProcessPoolExecutor for evaluation isolation | OpenEvolve: `process_parallel.py` with `ProcessPoolExecutor` |

---

## Key Reference Patterns Worth Adopting

### From ShinkaEvolve (strongest engineering reference):
1. `shinka/wandb_logging.py` — W&B integration with gen/score/cost tracking
2. `shinka/database/dbase.py:107-143` — `db_retry` decorator with exponential backoff
3. `shinka/llm/constants.py` — env-tuned LLM backoff constants
4. `shinka/database/async_dbase.py:170-188` — deadlock monitor background task
5. `shinka/configs/` — 5 Hydra config groups for experiment composition
6. `mkdocs.yml` + `docs/reference/` — mkdocstrings API docs

### From EvoX:
1. `src/evox_ext/autoload_ext.py:1-98` — PEP 420 namespace plugin auto-discovery at import time
2. `docs/` — Sphinx + autodoc2 + bilingual (EN+中文) + Jupyter notebook tutorials

### From DGM:
1. `llm.py:88` — `@backoff.on_exception(backoff.expo, (openai.RateLimitError, openai.APITimeoutError))` — clean library-based retry

### From OpenEvolve:
1. `process_parallel.py` — ProcessPoolExecutor for CPU-bound evaluation with graceful shutdown
2. `utils/async_utils.py` — `TaskPool` class with semaphore-gated `create_task`/`wait_all`/`cancel_all`

### From MLEvolve:
1. `config/__init__.py` — `OmegaConf.structured(Config)` for schema-validated config merging

---

## Summary

**OmniEvolve leads in**: Deterministic lock file, property-based testing, benchmark CI, typed exception hierarchy (exists), design documentation depth.

**OmniEvolve trails in**: Wired-up structured logging, wired-up plugin system, actual exception usage, retry library adoption, API documentation, experiment tracking, config reproducibility.
