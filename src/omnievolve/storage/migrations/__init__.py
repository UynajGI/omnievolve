"""数据库迁移框架.

S1-03: 实现 schema_version 与迁移框架
- 空库初始化
- 版本检测
- 正向迁移
- 幂等执行
"""

from __future__ import annotations

import logging
from pathlib import Path

from omnievolve.storage.db import Database

logger = logging.getLogger(__name__)

# 当前 schema 版本
CURRENT_VERSION = 2


def get_schema_version(db: Database) -> int:
    """获取当前数据库的 schema 版本."""
    try:
        row = db.fetchone("SELECT MAX(version) as v FROM schema_version")
        if row and row["v"] is not None:
            return row["v"]
    except Exception:
        # 表不存在，说明是空库
        pass
    return 0


def _ensure_schema_version_table(db: Database) -> None:
    """确保 schema_version 表存在."""
    db.execute("""
        CREATE TABLE IF NOT EXISTS schema_version (
            version             INTEGER PRIMARY KEY,
            applied_at          TEXT DEFAULT (datetime('now')),
            description         TEXT
        )
    """)


def _get_migration_sql(version: int) -> str:
    """获取指定版本的迁移 SQL."""
    # 从 migrations 目录读取 SQL 文件
    migrations_dir = Path(__file__).parent
    migration_file = migrations_dir / f"v{version:03d}_initial.sql"

    if version == 1:
        # v001: 初始 schema
        schema_file = Path(__file__).parent.parent / "schema.sql"
        if schema_file.exists():
            return schema_file.read_text(encoding="utf-8")

    if migration_file.exists():
        return migration_file.read_text(encoding="utf-8")

    raise ValueError(f"Migration file not found for version {version}")


def migrate(db: Database, target_version: int | None = None) -> int:
    """执行数据库迁移.

    Args:
        db: 数据库连接
        target_version: 目标版本，None 表示迁移到最新版本

    Returns:
        迁移后的版本号
    """
    if target_version is None:
        target_version = CURRENT_VERSION

    _ensure_schema_version_table(db)
    current = get_schema_version(db)

    if current >= target_version:
        logger.debug(f"Database already at version {current}, target {target_version}")
        return current

    logger.info(f"Migrating database from version {current} to {target_version}")

    for version in range(current + 1, target_version + 1):
        try:
            sql = _get_migration_sql(version)

            with db.transaction() as conn:
                # 执行迁移 SQL（跳过 PRAGMA 语句，因为已在连接层设置）
                statements = _split_sql(sql)
                for stmt in statements:
                    stmt = stmt.strip()
                    if stmt and not stmt.upper().startswith("PRAGMA"):
                        conn.execute(stmt)

                # 记录版本
                conn.execute(
                    "INSERT INTO schema_version (version, description) VALUES (?, ?)",
                    (version, f"Migration to v{version}"),
                )

            logger.info(f"Applied migration v{version}")

        except Exception as e:
            logger.error(f"Migration to v{version} failed: {e}")
            raise

    return target_version


def _split_sql(sql: str) -> list[str]:
    """分割 SQL 语句（简单实现，处理分号分隔）."""
    statements = []
    current = []
    in_string = False
    string_char = None

    for char in sql:
        if in_string:
            current.append(char)
            if char == string_char:
                in_string = False
        elif char in ("'", '"'):
            in_string = True
            string_char = char
            current.append(char)
        elif char == ";":
            stmt = "".join(current).strip()
            if stmt:
                statements.append(stmt)
            current = []
        else:
            current.append(char)

    # 处理最后一个语句
    stmt = "".join(current).strip()
    if stmt:
        statements.append(stmt)

    return statements


def initialize_database(db: Database) -> None:
    """初始化数据库（创建所有表）.

    这是 migrate() 的便捷封装，确保数据库就绪。
    """
    migrate(db)


def check_fts5_support(db: Database) -> bool:
    """检测 FTS5 支持.

    S1-12: 配置 SQLite FTS5 能力检测与降级
    """
    try:
        db.execute("CREATE VIRTUAL TABLE IF NOT EXISTS _fts5_test USING fts5(content)")
        db.execute("DROP TABLE IF EXISTS _fts5_test")
        return True
    except Exception:
        logger.warning("FTS5 not supported, full-text search will be disabled")
        return False


def create_fts_tables(db: Database) -> bool:
    """创建 FTS5 表（如果支持）.

    独立 FTS 表 + UNINDEXED entity_id 列 + 应用层写入。
    entity_id 不被索引（不可搜索），但可被 SELECT/JOIN 使用。

    Returns:
        是否成功创建
    """
    if not check_fts5_support(db):
        return False

    try:
        db.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS thought_fts USING fts5(
                entity_id UNINDEXED,
                content,
                mechanism_tags,
                tokenize='unicode61'
            )
        """)
        db.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
                entity_id UNINDEXED,
                content,
                tokenize='unicode61'
            )
        """)
        return True
    except Exception as e:
        logger.warning(f"Failed to create FTS tables: {e}")
        return False


def index_thought_fts(
    db: Database, thought_id: str, content: str, mechanism_tags: str = ""
) -> None:
    """向 thought_fts 写入索引（应用层触发）."""
    try:
        db.execute(
            "INSERT INTO thought_fts (entity_id, content, mechanism_tags) VALUES (?, ?, ?)",
            (thought_id, content, mechanism_tags),
        )
    except Exception:
        logger.debug("Failed to index thought in FTS", exc_info=True)


def index_memory_fts(db: Database, memory_id: str, content: str) -> None:
    """向 memory_fts 写入索引（应用层触发）."""
    try:
        db.execute(
            "INSERT INTO memory_fts (entity_id, content) VALUES (?, ?)",
            (memory_id, content),
        )
    except Exception:
        logger.debug("Failed to index memory in FTS", exc_info=True)
