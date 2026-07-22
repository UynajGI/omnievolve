# 向量配置与迁移文档

> S6-17: 编写向量配置与迁移文档

## 架构概览

OmniEvolve 的向量检索系统支持三种后端：

```
┌─────────────────────────────────────┐
│          Hybrid Retriever           │
│   (FTS5 + Vector 融合排序)           │
├─────────────────────────────────────┤
│  FTS5 BM25    │  Vector Backend     │
│  (关键词检索)  │  (语义检索)          │
├───────────────┼─────────────────────┤
│               │  NumPy (精确检索)    │
│               │  zvec (近似检索)     │
└───────────────┴─────────────────────┘
```

## 安装

```bash
# 仅 NumPy fallback（默认，零额外依赖）
pip install -e .

# zvec 加速（百万级向量，HNSW ANN）
pip install -e ".[vector]"    # 安装 zvec>=0.3

# 本地 Embedding（无需外部 API）
pip install -e ".[local-embed]"
```

> **自动检测**: CLI 启动时调用 `create_vector_backend(prefer_zvec=True)`，自动检测 zvec 是否可用。
> 可用则使用 HNSW ANN，否则透明回退 NumPy 精确检索。无需手动配置。

## 配置

向量后端通过 `create_vector_backend(prefer_zvec=True)` 自动选择，无需手动配置。
如需显式控制，可在 `omnievolve.toml` 中配置：

```toml
[vector]
# 后端选择: "numpy" | "zvec"  (默认自动检测)
backend = "numpy"

# Embedding 配置
[vector.embedding]
# 提供者: "openai" | "local" | "fake"
provider = "openai"
model = "text-embedding-3-small"

# zvec 配置（仅 backend="zvec" 时需要）
[vector.zvec]
dimension = 1536
metric = "cosine"       # cosine / l2 / ip
m = 16                  # HNSW 双向链接数
ef_construction = 200   # HNSW 构建候选列表大小
```

## Embedding Profile

每个可索引实体类型对应一个 EmbeddingProfile：

```python
from omnievolve.utils.embedding import EmbeddingProfile

# 代码嵌入
code_profile = EmbeddingProfile(
    name="code",
    provider="openai",
    model="text-embedding-3-small",
    chunk_size=2000,
    overlap=200,
)

# 思想嵌入
thought_profile = EmbeddingProfile(
    name="thought",
    provider="openai",
    model="text-embedding-3-small",
    chunk_size=500,
    overlap=50,
)
```

## 索引生命周期

### 1. 生产（Enqueue）

候选创建或代码修改时自动入队：

```sql
INSERT INTO vector_index_job (entity_type, entity_id, status)
VALUES ('candidate', 'abc123', 'pending')
```

### 2. 消费（Indexer）

`VectorIndexer` 消费 outbox 中的任务：

```python
from omnievolve.storage.vector_indexer import VectorIndexer

indexer = VectorIndexer(db, embedder, vector_store)
indexer.process_batch(batch_size=100)
```

### 3. 修复（Reconcile）

检测并修复不一致：

```python
indexer.reconcile()  # 扫描 pending + 孤儿向量
```

## 迁移

### NumPy → zvec

当向量数量超过 10 万时，建议从 NumPy 迁移到 zvec：

```bash
# 1. 安装 zvec (0.6+)
pip install -e ".[vector]"

# 2. 无需修改配置 — create_vector_backend(prefer_zvec=True) 自动检测

# 3. 触发重建
omnievolve recover  # 检测到 backend 变更，自动触发 reindex
```

> **zvec 0.6 API 注意**: 适配器使用 `zvec.create_and_open(path, schema)` 创建集合，
> `Collection.upsert([Doc(...)])` 插入，`Collection.query(queries=Query(...), topk=N)` 查询。
> COSINE metric 返回距离 (0=相同)，适配器自动转换为相似度 (1.0=相同)。

### Embedding 模型变更

当切换 Embedding 模型时（如 `text-embedding-3-small` → `text-embedding-3-large`）：

```bash
# 1. 更新配置中的 embedding.model
# 2. 增加 profile version
# 3. 运行修复以重建所有向量
omnievolve recover
```

> **注意**: 模型变更会导致所有现有向量失效。索引器会检测到 `embedding_profile` 版本变更并触发全量重建。

## 性能基准

| 后端 | 1K 向量 | 10K 向量 | 100K 向量 | 1M 向量 |
|------|---------|----------|-----------|---------|
| NumPy | ~1ms | ~10ms | ~100ms | ~1s |
| zvec-HNSW | ~0.1ms | ~0.5ms | ~1ms | ~5ms |

## 故障排查

### 向量索引延迟

如果搜索返回的结果与预期不符：

```bash
# 检查 outbox 积压
sqlite3 .omnievolve/data.db \
  "SELECT status, COUNT(*) FROM vector_index_job GROUP BY status"

# 手动触发消费
omnievolve recover
```

### 内存不足

NumPy 后端将所有向量加载到内存中。如果向量数量超过可用内存：

1. 切换到 zvec 后端（磁盘索引）
2. 或减少向量维度（如使用较小的 Embedding 模型）
