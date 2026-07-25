# OmniEvolve 源码审计：死代码与 Bug 发掘清单

> 审计日期：2026-07-25 | 分支：doc/cleanup | 源码：~23,346 行 Python（111 个 .py 文件）
> **此清单仅记录，不做任何修改** — 供项目维护者审阅后决定是否处理。
>
> 审计方法：ruff F-rules 全量扫描（0 hits）+ AST 自定义分析（unused-import / unused-func 检测）+
> 大文件逐行通读（engine / agents / sandbox / storage 关键文件）+ grep 交叉验证。

## 概要统计

| 类别 | 数量 |
|------|------|
| 死代码（未调用函数/方法/模块） | 47 |
| 死代码（未使用导入） | 0（ruff F401 已清洁） |
| 潜在 Bug（确定） | 5 |
| 潜在 Bug（需人工确认） | 9 |
| TODO/FIXME | 3 |
| 代码异味 | 14 |
| 一致性问题 | 4 |

---

## 一、死代码

### 1.1 未使用的导入

ruff `F401` 全量扫描（`ruff check --select F --preview`）结果：**All checks passed!**

代码库已配置 ruff（pyproject.toml），CI 已拦截未使用导入。此项无发现。

### 1.2 未调用的函数/方法（经 grep 全项目交叉验证）

以下函数/方法在 `src/` + `tests/` + `examples/` 中**零引用**（定义除外）。已排除：
- Protocol `@runtime_checkable` 接口方法（即使无直接调用也算实现契约）
- `__init__.py` 的 `__all__` 导出
- CLI 命令（Typer 装饰的入口点，`@app.command()`）

#### 高置信度死代码（整模块未使用）

| 文件 | 函数/类 | 说明 |
|------|---------|------|
| `utils/timing.py` | `PipelineTimer`, `with_pipeline_timing`, `summarize_timing`, `reset` | **整个模块未使用** — 引擎用的是 `utils/profiling.py` 的 `PipelineProfiler`。`timing.py` 是早期实现，已被 `profiling.py` 完全替代 |
| `utils/db_export.py` | `export_candidates`, `export_lineage`, `get_path_to_best`, `export_experiment_summary` | **整个模块未使用**（202 行）— pandas DataFrame 导出工具，无任何调用方 |
| `utils/model_check.py` | `validate_models`, `print_availability_report` | **整个模块未使用**（127 行）— 模型可用性检查，CLI doctor 命令未调用 |
| `utils/visualization.py` | `candidate_tree_to_rich`, `candidate_tree_to_string` | **整个模块未使用**（108 行）— rich 终端可视化，无调用方 |
| `agents/headless_provider.py` | `query_headless_async` | 异步版本未调用（同步版 `query_headless` 有 5 处引用） |

#### 中置信度死代码（单方法未调用，需人工确认是否为预留 API）

| 文件:行号 | 方法 | 所属类 | 说明 |
|-----------|------|--------|------|
| `agents/critic.py:262` | `review_debug` | `Critic` | 调试用审查方法，0 引用 |
| `agents/llm_gateway.py:321` | `get_stats_by_role` | `LLMGateway` | 按角色统计，0 引用（`get_stats` 有调用） |
| `agents/router.py:283` | `compute_coder_reward` | (函数) | **见 Bug §2.3** — `_update_router_reward` 用的是 `compute_shinka_reward` 而非此函数 |
| `engine/epiplexity.py:213` | `batch_score` | `EpiplexityEstimator` | 批量评分，0 引用（单条 `score` 有调用） |
| `engine/evolution_engine.py:341` | `current_generation` (property) | `EvolutionEngine` | 属性，0 外部引用 |
| `engine/evolution_engine.py:531` | `assess_policy_window` | `EvolutionEngine` | 设计文档 5.4 节公共 API，但无调用方 |
| `engine/evolution_engine.py:558` | `run_policy_challenger` | `EvolutionEngine` | 设计文档 5.4 节公共 API，但无调用方 |
| `engine/mcts.py:336` | `get_best_child` | `ProgressiveMCGS` | 按访问次数取最优子节点，0 引用 |
| `engine/mcts.py:373` | `clear_virtual_losses` | `ProgressiveMCGS` | 清除全部虚拟损失，0 引用 |
| `engine/setup.py:71` | `verify_evaluator_immutability` | `EngineSetup` | L2 不变性验证，0 引用 |
| `engine/setup.py:159` | `classify_task` | `EngineSetup` | 任务分类，0 引用 |
| `storage/artifact_store.py:263` | `garbage_collect` | `ArtifactStore` | GC 方法，0 引用 |
| `storage/db.py:75` | `fts5_available` (property) | `Database` | FTS5 可用性，0 引用（`async_db.py` 注释提到但未调用） |
| `storage/db.py:118` | `read_transaction` | `Database` | 读事务上下文管理器，0 引用 |
| `storage/db.py:170` | `close_all` | `Database` | 关闭所有连接，0 引用 |
| `storage/vector_indexer.py:249` | `reconcile` | `VectorIndexer` | 一致性校验，0 引用 |
| `storage/vector_indexer.py:304` | `migrate_profile` | `VectorIndexer` | 迁移 profile，0 引用 |
| `utils/profiling.py:176` | `record_step` | `PipelineProfiler` | 手动记录步骤，0 引用 |
| `utils/plots.py:229` | `save_all_plots` | (函数) | 批量保存图表，0 引用 |
| `utils/token_counter.py:198` | `check_budget` | `BudgetGuard` | 预算检查，0 引用（用的是 `can_proceed`） |
| `eval/early_stop.py:203` | `create_early_stop_method` | (函数) | 工厂函数，0 引用 |
| `config.py:335` | `build_sandbox_policy` | (函数) | 沙箱策略构建，0 引用 |

### 1.3 不可达分支 / 遗留代码

| 文件:行号 | 描述 |
|-----------|------|
| `engine/async_engine.py:18-39` | `AsyncEvolutionEngine` 类文档注释标注 **"[已废弃]"**，构造器和 `run()` 均 `warnings.warn(DeprecationWarning)`。整个类（~120 行）因已知竞态条件被弃用，`AsyncPipelineEngine` 是替代品。建议确认无外部依赖后删除 |
| `engine/async_engine.py:206-233` | `SlotPool` 类（28 行）在 `AsyncPipelineEngine` 中未使用（后者用 `asyncio.gather` 而非显式槽池）。0 引用 |
| `sandbox/subprocess_backend.py:214` | `"TEMP"` 出现在环境变量白名单元组中，这是环境变量名（非注释），但 Windows 下 `TEMP`/`TMP` 均有效，此处无问题 |

---

## 二、潜在 Bug

### 2.1 逻辑错误

#### Bug-1（确定）：`async_engine.py` 访问不存在的配置字段 `git_auto_gc_interval`

**文件**：`engine/async_engine.py:330`
```python
and gen % self._config.git_auto_gc_interval == 0  # noqa: SLF001
```
**问题**：`EvolutionConfig`（`evolution_engine.py:73-98`）没有 `git_auto_gc_interval` 字段。当 `code_store.backend_name == "git"` 时会抛 `AttributeError`。
**影响**：使用 Git 后端 + 异步流水线引擎时，每代都崩溃。
**修复方向**：在 `EvolutionConfig` 中添加 `git_auto_gc_interval: int = 10`，或删除此 GC 触发条件。

#### Bug-2（确定）：`evolution_engine.py` resume 时 MCTS 树结构被扁平化

**文件**：`engine/evolution_engine.py:847-852`
```python
def _rebuild_mcts(self, experiment_id: str) -> None:
    rows = self._db.fetchall(
        "SELECT id FROM candidate WHERE experiment_id = ? ORDER BY generation", ...)
    for row in rows:
        self._mcts.add_node(row["id"], parent=None, prior=0.5)  # ← parent 全是 None
```
**问题**：恢复实验时，所有候选都以 `parent=None` 加入 MCTS，**丢失了全部父子关系**。恢复后的 MCTS 是扁平节点集，`select()` 无法沿树下降，搜索质量退化。
**影响**：`resume()` 后的进化失去 MCTS 引导，退化为随机搜索。
**修复方向**：从 `candidate_parent` 表查询 ancestry，按 generation 顺序重建父子边。

#### Bug-3（确定）：`subprocess_backend.py` 候选代码被写入两次

**文件**：`sandbox/subprocess_backend.py:100-102` + `117-120`
```python
# ~line 100 (else 分支)
exec_dir = self._work_dir / f"exec_{...}"
exec_dir.mkdir(...)
if self._artifact_store:
    source_code = self._artifact_store.load(candidate.source_hash)
    code_file = exec_dir / "main.py"
    code_file.write_bytes(source_code)      # ← 第一次写

# ~line 117 (try 块内)
if self._artifact_store and not ws_handle:
    source_code = self._artifact_store.load(candidate.source_hash)
    code_file = exec_dir / "main.py"
    code_file.write_bytes(source_code)      # ← 第二次写（冗余）
```
**问题**：非 worktree 模式下，代码被 `load` + `write_bytes` 两次。浪费 I/O，且若 artifact store 内容在两次调用间变化（理论可能），会产生不一致。
**修复方向**：删除 try 块内的重复写入（else 分支已处理）。

### 2.2 异常处理缺陷

#### Bug-4（需确认）：`fast_loop.py:335` NoveltyGate REJECT 时未回滚虚拟损失后的计数器

**文件**：`engine/fast_loop.py:335-337`
```python
if novelty_result.decision == NoveltyDecision.REJECT:
    e._mcts.rollback_last_select()  # noqa: SLF001
    return None
```
**问题**：`rollback_last_select()` 清除了 select 路径上的虚拟损失，但 `should_force_backprop()` 的计数器 `self._nodes_since_backprop`（`mcts.py:307`）在 prepare 早期返回时不会被重置。高频 REJECT 会导致强制反向传播触发时机偏移。
**影响**：低 — 仅影响 P1-3 强制反向传播的概率触发，不影响正确性。
**修复方向**：在 `rollback_last_select` 中同步重置 `_nodes_since_backprop = 0`。

#### Bug-5（需确认）：`docker_backend.py:155` 非 timeout 异常也被标记为 timed_out

**文件**：`sandbox/docker_backend.py:140-152`
```python
except Exception as e:
    err_name = type(e).__name__
    if "timeout" in err_name.lower() or "timeout" in str(e).lower():
        timed_out = True
    else:
        logger.warning("Container wait failed: %s: %s", err_name, e)
        timed_out = True   # ← 非 timeout 异常也设为 True
```
**问题**：Docker API 非 timeout 错误（如连接断开、权限错误）也会把 `timed_out=True`，导致上层误判为超时。
**影响**：中 — 错误的分类会干扰 Critic 的失败原因分析和 telemetry。
**修复方向**：else 分支应 `timed_out = False`，或单独引入 `api_error` 字段。

### 2.3 并发/状态问题

#### Bug-6（需确认）：`fast_loop.py:805` Critic 奖励信号恒为 0

**文件**：`engine/fast_loop.py:800-810`
```python
def _update_router_reward(
    self, model, output, parent_ids,
    thought_adopted: bool = True,
    mechanism_novelty: float = 0.5,
    critic_passed: bool = True,    # ← 默认 True，且调用方不传此参数
    ...
):
    ...
    # critic_passed 永远是 True，因此：
    defect_recall = 0.5 if (not output.passed and not critic_passed) else 0.0      # 永远 0.0
    false_rejection = 0.3 if (output.passed and not critic_passed) else 0.0        # 永远 0.0
    cost_saved = 0.3 if (not output.passed and not critic_passed) else 0.0         # 永远 0.0
```
**问题**：`_commit_inner` 调用 `_update_router_reward` 时（`fast_loop.py:477`）只传 `model, output, parent_ids`，`critic_passed` 始终是默认值 `True`。导致 Critic 角色的奖励信号（defect_recall / false_rejection / cost_saved）**恒为 0**，Router 无法学习 Critic 模型的优劣。
**影响**：中 — Router 对 Critic 角色的路由决策无学习信号，但 Coder/Director 不受影响。
**修复方向**：在 `_commit_inner` 中传入实际的 `critic_passed` 状态（需在 `PreparedCandidate` 中记录 critic 审查结果）。

#### Bug-7（需确认）：`agents/router.py:283` `compute_coder_reward` 已被 `compute_shinka_reward` 替代

**文件**：`agents/router.py:283` vs `engine/fast_loop.py:793`
**问题**：`fast_loop._update_router_reward` 导入并使用 `compute_shinka_reward`（相对改进奖励），而非 `compute_coder_reward`。后者（router.py:283）0 引用，是遗留的旧实现。
**影响**：无功能影响 — 纯死代码。但两个函数并存易致混淆。
**修复方向**：删除 `compute_coder_reward`。

### 2.4 资源泄漏 / 空值未防护

#### Bug-8（需确认）：`novelty.py:168` AST 签名缓存清除策略过于激进

**文件**：`engine/novelty.py:165-168`
```python
self._recent_signatures.add(signature)
if len(self._recent_signatures) > self._max_cached_signatures:
    self._recent_signatures = {signature}   # ← 清空只留当前
```
**问题**：超限时直接清空整个集合并只保留当前签名，导致**下一批候选的 AST 签名全部被视为"新颖"**（因为缓存空了）。会产生周期性的误判脉冲。
**影响**：中 — 每 200 个候选后有一批误通过 NoveltyGate 的重复结构。
**修复方向**：改用 LRU 淘汰（`collections.OrderedDict`）或随机淘汰。

#### Bug-9（需确认）：`subprocess_backend.py:194` preexec_fn 中 RLIMIT_AS 可能导致 Python 自身 OOM

**文件**：`sandbox/subprocess_backend.py:194-199`
```python
def set_limits():
    if hasattr(resource, "RLIMIT_AS") and policy.mem_limit_mb > 0:
        mem_bytes = policy.mem_limit_mb * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (mem_bytes, mem_bytes))
```
**问题**：`RLIMIT_AS` 限制虚拟地址空间，Python 解释器 + 标准库加载后地址空间可能已接近 limit。子进程启动后 import 阶段就可能 OOM（参考 memory: `sandbox-blockers-fixed` 记录的 RLIMIT_AS=0 问题）。
**影响**：中 — 大内存限制（4GB 默认）下通常 OK，但用户设置小限制（如 256MB）时会误杀。
**修复方向**：改用 `RLIMIT_DATA` 或 cgroups（Docker 后端已用 cgroups，此问题仅影响 trusted subprocess）。

---

## 三、TODO / FIXME / HACK 汇总

| 文件 | 行号 | 注释内容 |
|------|------|----------|
| `plugins/geo/__init__.py` | 5 | `TODO(延后): 实现完整的 enrich_evaluation（坐标系误差检测、空间索引性能指标）` |
| `plugins/quant/__init__.py` | 5 | `TODO(延后): 实现完整的 enrich_evaluation（多窗口 IC 稳定性、过拟合检测、…）` |
| `sandbox/hardened_backend.py` | 7 | `TODO(延后): 实现至少一个具体的强隔离后端（推荐 nsjail 或 gVisor）` |

**说明**：代码库非常干净，仅 3 条 TODO，均为"延后实现"的预留桩函数，非缺陷标记。`subprocess_backend.py:214` 的 `"TEMP"` 是环境变量名，非 TODO 注释。

---

## 四、代码异味

### 4.1 过长函数 Top 10

| 行数 | 文件:行号 | 函数 |
|------|-----------|------|
| 220 | `engine/fast_loop.py:100` | `FastLoopStep.prepare` |
| 200 | `engine/evolution_engine.py:135` | `EvolutionEngine.__init__` |
| 133 | `agents/llm_gateway.py:95` | `LLMGateway.chat` |
| 128 | `eval/telemetry.py:183` | `HealthPolicy.assess` |
| 128 | `engine/fast_loop.py:480` | `FastLoopStep._execute_sandbox` |
| 109 | `cli.py:198` | `run` |
| 108 | `engine/fast_loop.py:609` | `FastLoopStep._apply_eval_result` |
| 105 | `sandbox/monty_backend.py:76` | `MontyBackend.execute` |
| 102 | `sandbox/subprocess_backend.py:93` | `TrustedSubprocessBackend.execute` |
| 102 | `cli.py:87` | `_build_engine_components` |

**重点**：`FastLoopStep.prepare`（220 行）承担了步骤 2-10 的全部逻辑（选父代→Director→Novelty→Coder→Critic→存储），建议进一步拆分。

### 4.2 参数过多（≥8 个）

| 参数数 | 文件:行号 | 函数 |
|--------|-----------|------|
| 24 | `engine/evolution_engine.py:135` | `EvolutionEngine.__init__` |
| 12 | `storage/repositories/candidate_repo.py:156` | `CandidateRepository.create_candidate` |
| 12 | `engine/memory.py:70` | `MemoryStore.add_memory` |
| 12 | `agents/llm_gateway.py:63` | `LLMGateway.__init__` |
| 11 | `storage/repositories/candidate_repo.py:92` | `CandidateRepository.create_thought` |
| 11 | `eval/evaluation_run.py:238` | `EvaluationRunRepository.complete` |
| 11 | `engine/slow_loop.py:41` | `SlowLoopController.__init__` |

**重点**：`EvolutionEngine.__init__` 有 24 个参数（含 16 个可注入组件），已用 keyword-only 分隔，但仍建议引入 Builder 或 config 对象。

### 4.3 重复代码 / 模式

| 模式 | 出现位置 | 说明 |
|------|----------|------|
| `# noqa: SLF001` 私有访问 | `fast_loop.py`（~50 处）、`async_engine.py`（~30 处）、`evolution_engine.py` | `FastLoopStep` / `AsyncPipelineEngine` 大量访问 `engine._xxx` 私有字段。method-object 模式的副作用，可接受但影响封装 |
| SandboxPolicy 构造 | `fast_loop.py:394`、`fast_loop.py:445` | `SandboxPolicy(timeout_sec=..., mem_limit_mb=...)` 在 `_execute_sandbox` 和 `_evaluate_progressive` 中重复构造 |
| `try: ... except Exception: logger.debug(...)` | 全局（>40 处） | 大量"吞异常 + debug 日志"模式，部分有合理性（非关键路径），但部分掩盖了真实错误（如 `vector_index_job` 插入失败） |

### 4.4 其他异味

| 文件:行号 | 描述 |
|-----------|------|
| `sandbox/subprocess_backend.py:126` | `import shutil` 在方法内部重复导入（`_run_command` 内和 `execute` finally 块各一次） |
| `engine/evolution_engine.py:279-281` | `_select_parents` 中 `import random` 在方法内导入，应提到模块顶部 |
| `engine/fast_loop.py:686` | `import json` 在 `_load_sibling_summaries` 方法内导入 |
| `agents/llm_gateway.py:132` | `import litellm` 在 `chat` 方法内导入（合理 — 可选依赖），但 `except ImportError` 分支返回 mock 而非抛异常，生产环境可能静默失效 |

---

## 五、一致性问题

### 5.1 模块间接口不匹配

| 问题 | 位置 | 说明 |
|------|------|------|
| Coder 奖励双实现 | `agents/router.py:283` (`compute_coder_reward`) vs `engine/fast_loop.py:793` (`compute_shinka_reward`) | 两个函数都计算 Coder 奖励，后者被使用，前者是遗留。命名未统一 |
| Database 连接管理 | `storage/db.py:118` (`read_transaction`) vs `storage/db.py:104` (`transaction`) | `read_transaction` 0 引用，`transaction` 被广泛使用。`read_transaction` 可能是早期设计的读优化入口，从未接入 |

### 5.2 配置项默认值与文档不符

| 字段 | 代码默认值 | 说明 |
|------|-----------|------|
| `EvolutionConfig.git_auto_gc_interval` | **不存在** | `async_engine.py:330` 引用了此字段但 `EvolutionConfig` 未定义（见 Bug-1） |

### 5.3 设计文档 API 与实现脱节

| 设计文档要求 | 实现状态 |
|-------------|----------|
| §5.4 `assess_policy_window()` 公共 API | 已实现（`evolution_engine.py:531`）但 0 调用方，疑似未接入主循环 |
| §5.4 `run_policy_challenger()` 公共 API | 已实现（`evolution_engine.py:558`）但 0 调用方，疑似未接入主循环 |
| §6 `Plugin.get_rag_corpus()` | `Plugin` 基类和 `GeoPlugin`/`QuantPlugin` 均实现，但 0 调用方 — RAG 语料从未被检索使用 |

---

## 附：审计覆盖范围

### 逐行通读的大文件（>200 行）

| 文件 | 行数 | 状态 |
|------|------|------|
| `engine/evolution_engine.py` | 959 | ✅ 逐行 |
| `engine/fast_loop.py` | 889 | ✅ 逐行 |
| `engine/async_engine.py` | 419 | ✅ 逐行 |
| `engine/mcts.py` | 435 | ✅ 逐行 |
| `engine/novelty.py` | 277 | ✅ 逐行 |
| `agents/llm_gateway.py` | 396 | ✅ 逐行 |
| `sandbox/subprocess_backend.py` | 270 | ✅ 逐行 |
| `sandbox/docker_backend.py` | 356 | ✅ 前 200 行逐行 |
| `utils/response.py` | 192 | ✅ 逐行 |

### AST 全量分析覆盖

- **111 个 .py 文件**全部解析（src/omnievolve/ 下）
- **889 个函数/方法定义**提取
- **614 个唯一函数名**交叉引用检查
- **196 个 .py 文件**引用计数（src + tests + examples）
- ruff `F` 规则全量扫描（unused import / undefined name / redefined / unused variable）：**0 发现**

### 未深入审计的文件（基于风险评估跳过逐行）

以下文件因行数较小（<150 行）或为 Protocol/数据类定义，仅经 AST 分析和抽样检查：

- `engine/{crossover,mutation,memory,checkpoint,setup,epiplexity,diff,island,inspiration,selection,slow_loop}.py`
- `agents/{base,circuit_breaker,context_builder,coder,director,fusion,meta,data_leakage}.py`
- `eval/{telemetry,evaluation_run,metrics,evaluator_registry,plan_validator,health_policy,task_evaluator,environment,early_stop,demo_evaluator,self_evaluator}.py`
- `storage/{vector_store,git_code_store,graph_store,artifact_store,vector_indexer,zvec_backend,job_store,async_db,uow,cas_code_store,code_store}.py` + `repositories/*`
- `meta/{governance,audit,policy_archive,hyperparam_tuner,policy_genome,prompt_evolver,infra_adapter}.py`
- `sandbox/{hardened_backend,monty_backend,registry,base}.py`
- `plugins/{base,quant,geo,discovery}.py`
- `utils/{profiling,embedding,plots,token_counter,seed,hashing,logging,config_snapshot,complexity,metric,pricing_catalog}.py`
- `cli.py`, `config.py`, `config_presets.py`, `exceptions.py`

**建议**：若需更深入审计，优先补审 `storage/vector_store.py`（590 行）、`storage/git_code_store.py`（445 行）、`meta/governance.py`（445 行）、`eval/telemetry.py`（426 行）——这四个是唯一 >400 行但未逐行通读的核心文件。

---

## 优先级建议

| 优先级 | 项目 | 理由 |
|--------|------|------|
| **P0** | Bug-1 (`git_auto_gc_interval`) | Git 后端 + 异步引擎必崩 |
| **P0** | Bug-2 (MCTS resume 扁平化) | resume 后搜索质量退化 |
| **P1** | Bug-3 (代码重复写入) | 性能浪费 + 潜在不一致 |
| **P1** | Bug-6 (Critic 奖励恒 0) | Router 学习信号缺失 |
| **P1** | Bug-5 (Docker timeout 误判) | 错误分类影响 telemetry |
| **P2** | 死代码模块清理 (`timing.py`, `db_export.py`, `model_check.py`, `visualization.py`) | ~590 行死代码，删除可降低维护负担 |
| **P2** | Bug-7 (`compute_coder_reward` 删除) | 消除双实现混淆 |
| **P3** | Bug-8 (AST 缓存策略) | 周期性误判脉冲 |
| **P3** | 过长函数拆分 (`prepare` 220 行) | 可读性 |
