# OmniEvolve v0.2 — 差距分析报告

> 审核日期：2026-07-20
> 审核范围：OmniEvolve v0.2 vs 参考项目 (OpenEvolve, ShinkaEvolve, EvoX, DGM, MLEvolve)
> 审核目标：识别工程化差距，按投入产出比排序改进建议

---

## 一、总体评估

| 维度 | 评级 | 说明 |
|------|------|------|
| 架构设计 | 🟢 优秀 | MCTS + Fast/Slow Loop + Governance 设计完善，超过各参考项目 |
| 代码质量 | 🟢 良好 | Ruff 0 errors, Mypy clean, 13.9K source LOC, properly typed |
| 测试覆盖 | 🟡 中等 | 188 tests, 3963 LOC (28% test/source ratio), 基准线但不到优秀 |
| 文档质量 | 🟡 中等 | 31 设计文档完整，但用户文档仅 3 篇 |
| CI/CD | 🟡 中等 | 基础 CI 存在，但缺乏集成测试、覆盖率追踪、多 Python 版本 |
| 工程化 | 🟡 中等 | 有质的提升空间：并发执行、基准测试、性能回归 |
| 参考项目借鉴 | 🔴 不足 | 参考项目的优秀工程模式未被充分吸收 |

---

## 二、详细差距矩阵

### 2.1 CI/CD 与自动化测试

| 差距 | OmniEvolve 现状 | 参考项目做法 | 优先级 |
|------|----------------|-------------|--------|
| **覆盖率追踪** | `pytest -q` 无覆盖率报告 | ShinkaEvolve: `--cov=shinka --cov-report=xml` + 上传 Coverage XML | P0 |
| **多 Python 版本** | 仅 3.12 | EvoX: 3.10-3.13 矩阵 | P0 |
| **集成测试分离** | 全部测试混在一起 | ShinkaEvolve: `@pytest.mark.requires_secrets` + 独立 integration workflow | P1 |
| **AI Code review** | 无 | OpenEvolve/ShinkaEvolve: Claude Code Action 自动 PR review | P1 |
| **PyPI 发布** | 无 | ShinkaEvolve: `pypi-release.yml` 自动发布 | P2 |
| **性能基准测试** | `examples/python_optimization/benchmark.py` 未集成 CI | EvoX: 单元测试覆盖核心算法性能 | P1 |
| **Hatch/PEP 621 构建完整性** | 仅有基本配置 | EvoX: 完整多平台构建矩阵 | P2 |

### 2.2 并行与异步执行

| 差距 | OmniEvolve 现状 | 参考项目做法 | 优先级 |
|------|----------------|-------------|--------|
| **异步 Fast Loop** | 同步串行生成候选 | OpenEvolve: `process_parallel.py` (887行, 异步并行评估) | **P0** |
| **并发 API 调用** | 同步 litellm 调用 | OpenEvolve: async HTTP + 重试/回退/熔断 | P0 |
| **Async sandbox** | 同步 subprocess.run | 理想: asyncio.create_subprocess_exec + timeout | P1 |
| **并行评估** | 单候选串行评估 | OpenEvolve: 进程池并行评估多个候选 | P1 |
| **非阻塞 MCTS** | 同步 select/expand/backprop | — | P2 |

### 2.3 测试质量与工程

| 差距 | OmniEvolve 现状 | 参考项目做法 | 优先级 |
|------|----------------|-------------|--------|
| **测试分类** | 无 pytest mark | ShinkaEvolve: `requires_secrets`, `models_dev_live` 等 mark | P1 |
| **假 LLM 重用** | 各测试文件各自定义 FakeLLM | 最佳实践: conftest 统一提供 | P1 |
| **突变测试** | 无 | — | P2 |
| **属性基测试** | hypothesis 在 dev deps 但未使用 | — | P2 |
| **性能回归测试** | 无基准测试 | EvoX: 单元测试含性能断言 | P1 |
| **并发/竞态测试** | `test_concurrency.py` 存在但有限 | OpenEvolve: `test_concurrent_island_access.py` | P1 |
| **长期 soak 测试** | P0 含 500-candidate soak | — | P2 |

### 2.4 错误处理与可观测性

| 差距 | OmniEvolve 现状 | 参考项目做法 | 优先级 |
|------|----------------|-------------|--------|
| **类型化异常** | `except Exception` (54处) 过于宽泛 | 最佳实践: 定义 `EvolutionError`, `SandboxError` 等 | P1 |
| **结构化日志** | 基础 logging, 部分 lazy %s | 理想: structlog 或 JSON logging | P2 |
| **健康端点** | 无运行时健康检查 | — | P2 |
| **指标导出** | TelemetryAggregator 在引擎内，无外部导出 | — | P2 |
| **审计完备性** | AuditReportGenerator 存在但验证有限 | — | P1 |

### 2.5 扩展性与插件

| 差距 | OmniEvolve 现状 | 参考项目做法 | 优先级 |
|------|----------------|-------------|--------|
| **插件实现** | QuantPlugin/GeoPlugin 为基础实现 | EvoX: 命名空间包扩展 (`evox_ext.*`) | P1 |
| **动态加载** | 无插件发现机制 | EvoX: `load_extension()` 自动发现并加载 `evox_ext` 命名空间包 | P1 |
| **评估器扩展** | 需手动注册 | 理想: 装饰器/发现机制 | P2 |
| **Sandbox 扩展** | 3种后端(fixed) | 理想: 可插拔后端接口 | P2 |

### 2.6 文档与示例

| 差距 | OmniEvolve 现状 | 参考项目做法 | 优先级 |
|------|----------------|-------------|--------|
| **用户指南** | 仅 release_notes + health + agent guide | OpenEvolve: 多篇示例文档 | P1 |
| **API 参考** | 无 (从源码 docstring 生成) | — | P2 |
| **交互式示例** | 无 notebook | — | P2 |
| **多领域示例** | 仅 `python_optimization` | OpenEvolve: 10+ 示例 (ARC, attention, circle_packing, blur...) | P1 |

### 2.7 可重复性与确定性

| 差距 | OmniEvolve 现状 | 参考项目做法 | 优先级 |
|------|----------------|-------------|--------|
| **依赖锁定** | 无 lock 文件 | OpenEvolve: `uv sync` + 隐式 lock | P1 |
| **种子管理** | 基础随机种子 | MLEvolve: `utils/seed.py` 全局种子管理 | P1 |
| **Docker 环境锁定** | 基础 Dockerfile | 理想: poetry/uv lock + pip freeze 校验 | P2 |
| **评估器确定性** | EvaluationRun idempotent 但种子未持久化 | — | P1 |

### 2.8 候选代码加速

| 差距 | OmniEvolve 现状 | 参考项目做法 | 优先级 |
|------|----------------|-------------|--------|
| **GPU 加速** | 纯 CPU (NumPy) | EvoX: JAX + Torch GPU 管线 | P2 |
| **批量评估** | 单候选 | EvoX: vmap 批量评估整个群体 | P2 |
| **JIT 编译** | 无 | EvoX: torch.compile + JAX jit | P2 |

---

## 三、按优先级排序的改进路线

### P0 (必须立即改进)

| # | 改进项 | 预期效果 | 参考模式 |
|---|--------|---------|---------|
| 1 | **异步 Fast Loop + 并行评估** | 10-50x 速度提升。当前每次生成一个候选，异步后批量并行。 | OpenEvolve `process_parallel.py` |
| 2 | **CI 覆盖率追踪 + 多 Python 版本** | 防止代码退化，确保跨版本兼容 | ShinkaEvolve CI + EvoX matrix |
| 3 | **种子全局管理 + 评估确定性** | 实验可复现，调试可追踪 | MLEvolve `utils/seed.py` |

### P1 (1-2 周内)

| # | 改进项 | 预期效果 | 参考模式 |
|---|--------|---------|---------|
| 4 | **类型化异常层次** | 调用方可精确捕获，减少宽泛 catch | — |
| 5 | **pytest 标记分类** | 测试可按类型(unit/integration/llm/soak)选择执行 | ShinkaEvolve markers |
| 6 | **共享假 LLM fixture** | 减少测试重复，提高可维护性 | — |
| 7 | **依赖锁定** | 构建确定性，避免"在我机器上能跑" | uv sync + lock |
| 8 | **集成测试 + LLM 测试分离** | CI 快慢分离，开发者体验提升 | ShinkaEvolve CI |
| 9 | **更多领域示例** | 降低新用户上手成本，验证框架通用性 | OpenEvolve 10+ examples |
| 10 | **并发竞态测试** | 保证 SQLite 并发安全 | OpenEvolve `test_concurrent_island_access.py` |

### P2 (按需/中远期)

| # | 改进项 | 预期效果 | 参考模式 |
|---|--------|---------|---------|
| 11 | 动态插件发现 | 第三方可扩展 | EvoX `load_extension()` |
| 12 | 属性基测试 | 发现边界情况 | hypothesis |
| 13 | 突变测试 | 测试质量量化 | mutmut / cosmic-ray |
| 14 | 结构化日志 | 生产可观测性 | structlog |
| 15 | GPU/JIT 加速 | 大规模进化加速 | EvoX JAX pipeline |
| 16 | PyPI 自动发布 | 版本管理自动化 | ShinkaEvolve pypi-release |
| 17 | AI Code Review Action | 自动 PR 审查 | OpenEvolve/ShinkaEvolve Claude Action |

---

## 四、关键发现详情

### 4.1 async 缺失 — 最大的单点瓶颈

OmniEvolve 是全线同步的。Fast Loop 中 `_evolve_one()` 调用 Director → Coder → Critic → Sandbox → Evaluator，每一步都是同步阻塞。在 8 个候选的群体中，全部串行完成。

**参考项目**：OpenEvolve 有 887 行的 `process_parallel.py`，通过 `concurrent.futures.ProcessPoolExecutor` 并行评估候选和 API 调用。
ShinkaEvolve 使用 asyncio 做 LLM 调用。

**建议方案**：将 `_evolve_one()` 改为 `async`，使用 `asyncio.gather` 并行生成/评估候选。
或者引入 `concurrent.futures.ThreadPoolExecutor` 做 I/O 并行。

### 4.2 CI 缺乏质量门禁

当前 CI 只检查：
- Ruff lint
- Mypy type check
- pytest -q（无覆盖率）
- Docker 构建验证

参考 ShinkaEvolve 的 CI 增加：
- **覆盖率追踪**: `--cov=omnievolve --cov-report=xml` + artifact upload
- **多版本矩阵**: Python 3.12-3.13
- **测试分类**: 快慢分离，集成测试单独 Job

### 4.3 测试模式

OmniEvolve 的测试设计良好（P0 门、架构不变量），但：
- 测试/源码比 28%（3963/13971），优秀项目 >50%
- 各测试文件重复定义 FakeLLM（5+ 处）
- 无基准测试 / 性能回归测试
- 无属性基测试

### 4.4 文档生态缺口

31 份设计文档是资产，但用户文档仅 3 篇：
- `docs/health_metrics.md`
- `docs/prompt_agent_guide.md`
- `docs/release_notes_v0.2.md`

缺少：入门教程、API 参考、多领域示例、最佳实践指南。

---

## 五、参考项目可复用模式清单

| 模式 | 来源 | 适用 OmniEvolve 模块 | 难度 |
|------|------|---------------------|------|
| 异步并行评估进程池 | OpenEvolve `process_parallel.py` | `engine/evolution_engine.py` | 中 |
| 检查点/恢复带版本化快照 | OpenEvolve `controller.py` | `engine/evolution_engine.py` | 低 |
| 多阶段引导进化管线 | OpenEvolve `controller.py` | `engine/` | 低 |
| LLM 调用账本与费用追踪 | OpenEvolve `api.py` | `agents/llm_gateway.py` | 低 |
| 命名空间包扩展系统 | EvoX `load_extension()` | `plugins/` | 中 |
| @jit 编译 + vmap 批量评估 | EvoX 核心 | `eval/` | 高 |
| 种子全局管理器 | MLEvolve `utils/seed.py` | `utils/` | 低 |
| Claude Code Action PR review | OpenEvolve/ShinkaEvolve CI | `.github/workflows/` | 低 |
| 覆盖率追踪 + 上传 | ShinkaEvolve CI | `.github/workflows/` | 低 |
| 测试标记分类 | ShinkaEvolve pytest marks | `tests/` | 低 |
| 结构化 JSON 评估输出 | OpenEvolve `evaluator.py` | `eval/task_evaluator.py` | 低 |
| uv 依赖管理 | ShinkaEvolve | `pyproject.toml` | 低 |
| 集成/单元测试分离 | OpenEvolve `tests/unit + tests/integration` | `tests/` | 低 |

---

## 六、执行建议

**立即（0-2 天）**：
1. 增加 CI 覆盖率追踪 → 建立覆盖基线
2. 添加 pytest 标记分类（unit/integration/soak）
3. 统一 FakeLLM fixture 到 conftest

**短期（1 周）**：
4. 种子全局管理（低风险高回报）
5. 类型化异常层次
6. 更多 OpenEvolve 风格的领域示例

**中期（2-4 周）**：
7. 异步 Fast Loop（最大单点性能提升）
8. 依赖锁定
9. 集成测试分离

---

## 七、总结

OmniEvolve v0.2 的架构设计（MCTS + Fast/Slow Loop + Governance）**超越**了所有参考项目。主要差距集中在**工程化实践**而非设计层面：

- **最强**：架构设计、类型安全、代码质量、文档设计
- **待改进**：并行执行、CI 质量门禁、测试深度、用户文档、示例生态

参考项目中，OpenEvolve 的异步模式和 EvoX 的扩展系统是最值得优先借鉴的模式。
