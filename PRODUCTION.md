# OmniEvolve 生产运维指南

> v0.2.0-beta | 735 tests | 70% coverage | ruff+mypy clean

## 快速健康检查

```bash
omnievolve doctor                              # 环境诊断
python -c "from omnievolve.sandbox.docker_backend import is_docker_available; print(is_docker_available())"
python -c "from omnievolve.storage.db import Database; d=Database(':memory:'); print(d.fts5_available)"
```

## 部署清单

| # | 检查项 | 命令/方法 |
|---|--------|-----------|
| 1 | Python 3.12+ | `python --version` |
| 2 | SQLite FTS5 | `sqlite3 :memory: 'CREATE VIRTUAL TABLE t USING fts5(x)'` |
| 3 | API key 配置 | `export DEEPSEEK_API_KEY="sk-..."` 或 `.env` |
| 4 | 配置文件 | `cp configs/omnievolve.toml.example omnievolve.toml` |
| 5 | 沙箱后端 | 本地: `trusted_subprocess`（默认）/ Docker: `docker` |
| 6 | 迁移执行 | `omnievolve migrate`（自动 v001→v002） |
| 7 | 快速冒烟 | `make test` (735 tests, ~36s) |
| 8 | LLM 连通性 | `make test-llm`（需 API key） |

## 运行时监控

### 关键指标

| 指标 | 来源 | 告警阈值 |
|------|------|---------|
| 候选成功率 | `evaluation_run.passed` | < 30% |
| 前沿提升 | `evaluation_run.primary_score` 窗口最大值 | 连续 3 窗口无提升 |
| API 成本 | `llm_call_ledger.cost_usd` | token_budget 耗尽 |
| 熔断器状态 | `CircuitBreaker.stats` | OPEN 状态 |
| 健康等级 | `meta_evaluation_window.alert_level` | CRITICAL |

### Prometheus 指标端点

```python
from omnievolve.eval.telemetry import DashboardDataExporter
metrics_text = exporter.export_prometheus(experiment_id)
# 输出：
# omnievolve_roi_score{experiment_id="..."} 0.012
# omnievolve_success_rate{experiment_id="..."} 0.85
# omnievolve_alert_level{experiment_id="..."} 0
```

### OpenTelemetry（可选）

```bash
pip install opentelemetry-api opentelemetry-sdk opentelemetry-exporter-otlp
export OTEL_EXPORTER_OTLP_ENDPOINT="http://localhost:4317"
# 自动追踪：Fast Loop 各步骤耗时、候选生成计数、评估分数
```

## 故障恢复

### 进程崩溃

```bash
# 每代自动持久化检查点到 experiment.checkpoint_data
# 崩溃后从中断处继续：
omnievolve run ./code.py -e eval:MyEvaluator -c config.toml --resume <experiment_id>
```

### 数据库损坏

```bash
# SQLite WAL 模式 + 每代检查点 = 最多丢失 1 代
sqlite3 .omnievolve/omnievolve.db "PRAGMA integrity_check"
# 如果损坏：从 .omnievolve/omnievolve.db-wal 恢复
```

### API 故障

熔断器自动断开，防止失控重试：
- 5 次连续失败 → OPEN（拒绝所有请求）
- 60s 后 → HALF_OPEN（允许一次试探）
- 试探成功 → CLOSED（恢复）

手动重置：
```python
from omnievolve.agents.circuit_breaker import CircuitBreaker
cb = CircuitBreaker()
# 熔断器状态会自动恢复，无需手动干预
```

### Token 预算耗尽

```bash
# 实验配置中设置
[evolution]
token_budget = 2_000_000  # 总 token 预算，耗尽后自动停止
```

## 性能基线

| 场景 | 指标 | 基线 |
|------|------|------|
| Tier 1 测试 | 735 tests | ~36s (CI) |
| Soak 50 代 | 200 候选, FakeLLM | ~2s |
| 真实 LLM 2 代 | heilbronn, deepseek-chat | ~30s |
| 单候选评估 | 沙箱执行 | < 5s (含 Docker 启动) |
| DB 写入 | 200 候选 | < 500ms |

## 安全边界

| 层级 | 说明 |
|------|------|
| **L2 永久禁止** | Task semantics / correctness tests / metric definitions / score formulas |
| **L1 需 replay** | Timeout schedule / resource allocation / build cache |
| **L0 自动可调** | Log format / tracing / temp dir |

## 已知限制

- SQLite 单机：不适用分布式场景（可接 PostgreSQL/ZVec 后端）
- AsyncEngine 完整并发需要基于文件的 DB（:memory: 在线程间不共享）
- Tier 2 LLM 测试需要 API key 手动运行
- Docker 集成测试需要 Docker daemon（CI matrix 待加）
