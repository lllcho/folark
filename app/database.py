import logging
from pathlib import Path

import aiosqlite

logger = logging.getLogger(__name__)

# 模块级数据库连接（单例）
_db: aiosqlite.Connection | None = None

SCHEMA_SQL = """
-- documents 表
CREATE TABLE IF NOT EXISTS documents (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid                TEXT UNIQUE NOT NULL,

    file_name           TEXT NOT NULL,
    file_path           TEXT UNIQUE NOT NULL,
    source_dir          TEXT,
    import_method       TEXT DEFAULT 'upload',
    file_type           TEXT NOT NULL,
    file_size           INTEGER,
    file_hash           TEXT UNIQUE,
    file_modified_time  DATETIME,

    title               TEXT,
    authors             JSON,
    thumbnail_path      TEXT,
    meta_data           JSON,

    summary             TEXT,

    is_missing          INTEGER DEFAULT 0,
    imported_time       DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- tags 表
CREATE TABLE IF NOT EXISTS tags (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid    TEXT UNIQUE NOT NULL,
    name    TEXT UNIQUE NOT NULL,
    color   TEXT DEFAULT '#409EFF'
);

-- document_tags 表
CREATE TABLE IF NOT EXISTS document_tags (
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    tag_id      INTEGER NOT NULL REFERENCES tags(id)      ON DELETE CASCADE,
    PRIMARY KEY (document_id, tag_id)
);

-- document_texts 表
CREATE TABLE IF NOT EXISTS document_texts (
    document_id INTEGER PRIMARY KEY REFERENCES documents(id) ON DELETE CASCADE,
    plain_text  TEXT,
    word_count  INTEGER DEFAULT 0
);



-- 索引
CREATE INDEX IF NOT EXISTS idx_documents_type      ON documents(file_type);
CREATE INDEX IF NOT EXISTS idx_documents_imported  ON documents(imported_time);
CREATE INDEX IF NOT EXISTS idx_documents_source    ON documents(source_dir);
CREATE INDEX IF NOT EXISTS idx_documents_missing   ON documents(is_missing);
CREATE INDEX IF NOT EXISTS idx_documents_filename  ON documents(file_name COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_documents_filesize  ON documents(file_size);
CREATE INDEX IF NOT EXISTS idx_documents_modified  ON documents(file_modified_time);


-- plugins 表
CREATE TABLE IF NOT EXISTS plugins (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT UNIQUE NOT NULL,
    version     TEXT NOT NULL,
    plugin_type TEXT NOT NULL DEFAULT 'builtin',  -- 'builtin' | 'community'
    enabled     INTEGER DEFAULT 1,
    config      JSON,
    task_handlers       JSON,  -- 存储处理器列表: [{"handler_name": "pdf_extract", "handler_type": "extract", "source_types": ["pdf"], "target_types": null, "handler_mode": "instant", "enabled": 1, "description": "..."}, ...]
    installed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- settings 表（用户自定义配置持久化）
CREATE TABLE IF NOT EXISTS settings (
    key        TEXT PRIMARY KEY,
    value      JSON NOT NULL,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- batch_jobs 表
CREATE TABLE IF NOT EXISTS batch_jobs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid            TEXT UNIQUE NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending',
    document_count  INTEGER NOT NULL DEFAULT 0,
    handlers        JSON NOT NULL,
    total_items     INTEGER NOT NULL DEFAULT 0,
    success_count   INTEGER NOT NULL DEFAULT 0,
    failed_count    INTEGER NOT NULL DEFAULT 0,
    skipped_count   INTEGER NOT NULL DEFAULT 0,
    created_at      DATETIME NOT NULL DEFAULT (datetime('now','localtime')),
    started_at      DATETIME,
    completed_at    DATETIME
);

-- batch_job_items 表
CREATE TABLE IF NOT EXISTS batch_job_items (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id          INTEGER NOT NULL REFERENCES batch_jobs(id) ON DELETE CASCADE,
    document_id     INTEGER NOT NULL,
    plugin_name     TEXT NOT NULL,
    handler_name    TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending',
    error_message   TEXT,
    started_at      DATETIME,
    completed_at    DATETIME
);

CREATE INDEX IF NOT EXISTS idx_batch_job_items_job_id ON batch_job_items(job_id);
CREATE INDEX IF NOT EXISTS idx_batch_job_items_status ON batch_job_items(job_id, status);
"""

# FTS5 虚拟表和触发器需要单独处理
FTS5_SETUP_SQL = """
CREATE VIRTUAL TABLE IF NOT EXISTS doc_search USING fts5(
    plain_text,
    content='document_texts',
    content_rowid='document_id'
);
"""

TRIGGER_AI_SQL = """
CREATE TRIGGER IF NOT EXISTS doc_text_ai AFTER INSERT ON document_texts BEGIN
    INSERT INTO doc_search(rowid, plain_text) VALUES (NEW.document_id, NEW.plain_text);
END;
"""

TRIGGER_AU_SQL = """
CREATE TRIGGER IF NOT EXISTS doc_text_au AFTER UPDATE ON document_texts BEGIN
    INSERT INTO doc_search(doc_search, rowid, plain_text) VALUES('delete', OLD.document_id, OLD.plain_text);
    INSERT INTO doc_search(rowid, plain_text) VALUES (NEW.document_id, NEW.plain_text);
END;
"""

TRIGGER_AD_SQL = """
CREATE TRIGGER IF NOT EXISTS doc_text_ad AFTER DELETE ON document_texts BEGIN
    INSERT INTO doc_search(doc_search, rowid, plain_text) VALUES('delete', OLD.document_id, OLD.plain_text);
END;
"""

# 当 document_tags 关联被删除后，自动清理不再关联任何文档的孤立标签
TRIGGER_ORPHAN_TAG_SQL = """
CREATE TRIGGER IF NOT EXISTS cleanup_orphan_tags AFTER DELETE ON document_tags BEGIN
    DELETE FROM tags WHERE id = OLD.tag_id
        AND NOT EXISTS (SELECT 1 FROM document_tags WHERE tag_id = OLD.tag_id);
END;
"""


def get_db() -> aiosqlite.Connection:
    """返回模块级的数据库连接单例"""
    if _db is None:
        raise RuntimeError("Database connection not initialized. Call init_db() first.")
    return _db


async def init_db(db_path: Path) -> None:
    """创建并保存 aiosqlite 连接，初始化数据库 Schema"""
    global _db

    logger.info("正在初始化数据库: %s", db_path)

    _db = await aiosqlite.connect(db_path)

    # 启用 WAL 模式
    await _db.execute("PRAGMA journal_mode=WAL")
    # 启用外键约束
    await _db.execute("PRAGMA foreign_keys=ON")

    # 执行主 Schema
    await _db.executescript(SCHEMA_SQL)

    # 创建 FTS5 虚拟表
    await _db.executescript(FTS5_SETUP_SQL)

    # 创建触发器（使用 IF NOT EXISTS）
    await _db.executescript(TRIGGER_AI_SQL)
    await _db.executescript(TRIGGER_AU_SQL)
    await _db.executescript(TRIGGER_AD_SQL)
    await _db.executescript(TRIGGER_ORPHAN_TAG_SQL)

    await _db.commit()
    logger.info("数据库 Schema 初始化完成")


async def close_db() -> None:
    """关闭数据库连接并清空模块级变量"""
    global _db

    if _db is not None:
        await _db.close()
        _db = None
        logger.info("数据库连接已关闭")
