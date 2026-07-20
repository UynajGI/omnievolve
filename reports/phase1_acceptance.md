# Phase 1 验收报告

**阶段：** Phase 1（S1-S4：存储层 + 沙箱 + 评估 + Candidate 图）
**验收日期：** 2026-07-20
**里程碑：** M1 (Storage & Sandbox) → M2 (Reproducible Core)

## Phase 1 验收清单

| # | 验收条件 | 状态 | 证据 |
|---|----------|------|------|
| 1 | 单任务执行 ≥500 个候选不丢已提交状态 | **PASS** | `test_p0_quality_gates.py::TestSoak500Candidates::test_500_candidate_soak` — 500 候选创建后 DB COUNT = 500 |
| 2 | kill -9 后不重复提交已完成 EvaluationRun | **PASS** | `test_p0_quality_gates.py::TestKill9Recovery::test_kill9_recovery_each_stage` — 3 阶段崩溃恢复 |
| 3 | 租约过期任务可重新认领 | **PASS** | `test_p0_quality_gates.py::TestJobLeaseReclaim::test_job_lease_expiry_and_reclaim` |
| 4 | 候选默认无法读取宿主 API Key/访问外网/越权挂载 | **PASS** | `test_p0_quality_gates.py::TestSandboxIsolation::test_docker_no_network_no_secret_no_privilege` |
| 5 | 任一结果可还原至 Artifact/Evaluator/Environment/Seed | **PASS** | `test_p0_quality_gates.py::TestAuditFullProvenance::test_audit_full_provenance` |

## 交付物清单

| 交付物 | 路径 | 状态 |
|--------|------|------|
| v0.2 schema 与迁移 | `storage/schema.sql` + `storage/migrations/` | ✓ |
| Artifact Store | `storage/artifact_store.py` (313 行) | ✓ |
| SandboxBackend | `sandbox/base.py` + `docker_backend.py` + `subprocess_backend.py` | ✓ |
| Evaluator Registry | `eval/evaluator_registry.py` (276 行) | ✓ |
| Demo evaluator | `eval/demo_evaluator.py` + `examples/python_optimization/` | ✓ |
| Candidate/Lineage/EvaluationRun | `storage/repositories/candidate_repo.py` + `eval/evaluation_run.py` | ✓ |
| Scheduler/Job Lease | `engine/scheduler.py` + `storage/job_store.py` | ✓ |
| GraphStore | `storage/graph_store.py` (304 行) | ✓ |
| UnitOfWork | `storage/uow.py` (136 行) | ✓ |

## 测试覆盖

- Schema 不变量测试：`tests/storage/test_schema.py` (10 tests)
- Artifact 完整性测试：`tests/storage/test_artifact_store.py` (18 tests)
- 并发测试：`tests/storage/test_concurrency.py` (13 tests)
- Scheduler 测试：`tests/engine/test_scheduler.py` (14 tests)
- Sandbox 测试：`tests/sandbox/test_sandbox.py` (15 tests)
- P0 质量门：`tests/test_p0_quality_gates.py` (相关 7 个)

## 结论

**Phase 1 验收通过。** 所有 5 项验收条件均有测试证据支持。
