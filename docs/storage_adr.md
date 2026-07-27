# 存储 ADR (Architecture Decision Record)

> S1-16: 编写存储 ADR 与运维诊断说明

## ADR-001: SQLite + WAL 作为主存储

**状态**: 已采纳
**日期**: 2026-07-20

### 背景

OmniEvolve v0.2 需要持久化候选代码、评估结果、血缘图和搜索状态。需要一个事务性、零运维、local-first 的存储方案。

### 决策

采用 **SQLite 3.40+ with WAL journal mode** 作为主存储：

- **WAL mode**: 支持读写并发，写者不阻塞读者
- **foreign_keys=ON**: 确保引用完整性
- **busy_timeout=5000ms**: 处理短期锁竞争
- **synchronous=NORMAL**: 平衡性能与安全性
- **cache_size=-64000**: 64MB 页面缓存

### 替代方案

| 方案 | 优点 | 缺点 | 决策 |
|------|------|------|------|
| PostgreSQL | 强大并发、丰富类型 | 需要外部服务，违背 local-first | 拒绝 |
| DuckDB | OLAP 友好 | 无 WAL 并发模型，不适合 OLTP | 拒绝 |
| SQLite rollback journal | 简单 | 写者阻塞读者 | 拒绝 |

### 影响

- 单机部署，零外部依赖
- 最多 1 写者 + N 读者并发
- 事务通过 `db.transaction()` 和 `uow.UnitOfWork` 管理

---

## ADR-002: SHA-256 内容寻址 Artifact Store

**状态**: 已采纳
**日期**: 2026-07-20

### 背景

候选代码需要持久化，且需要在不同实验间复用、去重、校验完整性。

### 决策

采用 **内容寻址存储 (CAS)**：

- 所有 Artifact 按 SHA-256 哈希存储：`<root>/sha256/ab/cd/<full_hash>`
- 原子写入：`tmpfile → fsync → rename`
- 去重：同一内容只存储一次（`INSERT OR IGNORE`）
- 完整性校验：加载时验证哈希匹配

### 影响

- 代码不可变，历史可审计
- 文件系统路径由哈希派生，无需中心化索引
- 损坏检测：哈希不匹配时抛出 `ValueError`

---

## ADR-003: 线程本地数据库连接

**状态**: 已采纳
**日期**: 2026-07-20

### 决策

每个线程持有独立 SQLite 连接（`threading.local()`），避免跨线程共享连接导致的并发问题。

### 影响

- 连接惰性创建，按需分配
- `Database.close()` 只关闭当前线程连接
- 线程池中的线程复用连接

---

## ADR-004: 可插拔代码存储后端（CAS / Git）

**状态**: 已采纳
**日期**: 2026-07-22

### 背景

v0.2 初期所有候选代码通过 `ArtifactStore`（SHA-256 CAS）存储。随着血缘深度增长，CAS 无法高效表达 ancestry、diff 和多父代合并（crossover），需要一种原生支持 DAG 的存储方案。

### 决策

引入 `CodeStore` Protocol 抽象层，提供两个可插拔后端：

| 后端 | `code_backend` | 存储 ref | 血缘 | 适用场景 |
|------|----------------|----------|------|----------|
| **CASCodeStore** | `"cas"` | SHA-256 哈希 | DB 外键关联 | 简单场景、最小依赖 |
| **GitCodeStore** | `"git"`（默认） | Git commit SHA | 原生 ancestry + worktree | 生产推荐、深血缘、crossover |

工厂函数 `create_code_store(settings, db)` 根据配置选择后端：

```python
from omnievolve.storage.code_store import create_code_store

# 配置 [storage] code_backend = "git"（默认）
store = create_code_store(settings, db)
```

`CodeStore` Protocol 统一接口：`store_snapshot` / `load_snapshot` / `materialize` / `diff` / `get_parents` / `merge` / `checkpoint`。

### GitCodeStore 细节

- **per-project 仓库**：每个实验（task_name）对应一个独立 bare repo（`.omnievolve/code.git`）
- **worktree 物化**：`materialize(ref)` 创建 Git worktree，沙箱直接 checkout，零拷贝
- **原生 diff**：`diff(parent, child)` 调用 `git diff`，精确 unified diff
- **多父代合并**：`merge(parent_refs)` 支持 crossover 场景的 ancestry 合并
- **自动 GC**：每 `git_auto_gc_interval` 代（默认 50）执行 `git gc`

### 影响

- 引擎通过 `CodeStore` Protocol 操作代码，与后端实现解耦
- Git 后端提供原生血缘 DAG，无需在 DB 中重建 ancestry
- CAS 后端保持兼容，适合极简部署

---

## 运维诊断

### 检查数据库完整性

```bash
sqlite3 .omnievolve/data.db "PRAGMA integrity_check;"
```

### 检查 WAL 文件大小

```bash
ls -lh .omnievolve/data.db-wal
# 超过 100MB 时执行 checkpoint
sqlite3 .omnievolve/data.db "PRAGMA wal_checkpoint(TRUNCATE);"
```

### 检查 Artifact 完整性

```bash
omnievolve recover <experiment_id>  # 扫描过期租约、未完成 Outbox、孤立 Artifact
omnievolve audit <experiment_id>    # 端到端审计（哈希、版本、缺失索引）
```

### 性能调优

- `cache_size`: 默认 64MB，大实验可调至 256MB
- `synchronous`: 默认 NORMAL，高可靠性需求可调至 FULL
- 定期 VACUUM：回收删除候选后的空间
