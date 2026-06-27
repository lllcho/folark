"""设置与系统信息 API。"""

import json
import logging
import os
import tomllib

from litestar import Router, get, patch, post
from litestar.exceptions import HTTPException
from litestar.status_codes import HTTP_400_BAD_REQUEST

from app.config import EDITABLE_KEYS, get_settings
from app.database import get_db

logger = logging.getLogger(__name__)


@get("/settings")
async def get_app_settings() -> dict:
    """返回当前应用配置信息（合并 DB 中的用户自定义值）。"""
    settings = get_settings()

    return {
        "data_root": str(settings.DATA_ROOT.resolve()),
        "library_root": str(settings.LIBRARY_ROOT.resolve()),
        "previews_root": str(settings.PREVIEWS_ROOT.resolve()),
        "db_path": str(settings.DB_PATH.resolve()),
        "log_dir": str(settings.LOG_DIR.resolve()),
        "port": settings.PORT,
        "log_level": settings.LOG_LEVEL,
        "max_upload_size": settings.MAX_UPLOAD_SIZE,
        "import_dir_whitelist": [str(p) for p in settings.IMPORT_DIR_WHITELIST],
        "document_extensions": sorted(settings.DOCUMENT_EXTENSIONS),
        "ebook_extensions": sorted(settings.EBOOK_EXTENSIONS),
        "text_extensions": sorted(settings.TEXT_EXTENSIONS),
        "image_extensions": sorted(settings.IMAGE_EXTENSIONS),
        "audio_extensions": sorted(settings.AUDIO_EXTENSIONS),
        "video_extensions": sorted(settings.VIDEO_EXTENSIONS),
        "archive_extensions": sorted(settings.ARCHIVE_EXTENSIONS),
    }


@get("/settings/about")
async def get_about_info() -> dict:
    """返回应用版本与数据统计信息。"""
    settings = get_settings()
    db = get_db()

    # 文档总数
    async with db.execute("SELECT COUNT(*) FROM documents") as cursor:
        row = await cursor.fetchone()
    document_count = row[0] if row else 0

    # 插件总数
    async with db.execute("SELECT COUNT(*) FROM plugins") as cursor:
        row = await cursor.fetchone()
    plugin_count = row[0] if row else 0

    # 数据库文件大小
    db_path = settings.DB_PATH.resolve()
    db_size = 0
    if db_path.exists():
        db_size = db_path.stat().st_size
        # 加上 WAL 和 SHM 文件
        for suffix in ("-wal", "-shm"):
            wal_path = db_path.parent / (db_path.name + suffix)
            if wal_path.exists():
                db_size += wal_path.stat().st_size

    # 文档库目录大小
    library_size = 0
    library_root = settings.LIBRARY_ROOT.resolve()
    if library_root.exists():
        for file_path in library_root.rglob("*"):
            if file_path.is_file():
                library_size += file_path.stat().st_size

    # 从 pyproject.toml 读取版本号
    app_version = "0.1.0"
    try:
        pyproject_path = os.path.join(os.path.dirname(__file__), "..", "..", "pyproject.toml")
        with open(pyproject_path, "rb") as f:
            pyproject = tomllib.load(f)
            app_version = pyproject.get("project", {}).get("version", "0.1.0")
    except Exception:
        pass

    return {
        "app_version": app_version,
        "database": {
            "path": str(db_path),
            "document_count": document_count,
            "plugin_count": plugin_count,
            "db_size": db_size,
        },
        "library": {
            "path": str(library_root),
            "size": library_size,
        },
    }


@patch("/settings")
async def update_settings(data: dict) -> dict:
    """更新用户自定义配置，写入 DB（重启后生效）。"""
    db = get_db()

    # 校验 key
    invalid_keys = set(data.keys()) - EDITABLE_KEYS
    if invalid_keys:
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail=f"不允许修改的配置项: {sorted(invalid_keys)}",
        )

    # 写入 DB
    for key, value in data.items():
        await db.execute(
            "INSERT OR REPLACE INTO settings (key, value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)",
            (key, json.dumps(value, ensure_ascii=False)),
        )
    await db.commit()

    return {"status": "ok", "updated_keys": sorted(data.keys())}


@post("/settings/reset/{key:str}")
async def reset_setting(key: str) -> dict:
    """删除 DB 中的配置项，恢复默认值（重启后生效）。"""
    if key not in EDITABLE_KEYS:
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail=f"不允许重置的配置项: {key}",
        )

    db = get_db()
    await db.execute("DELETE FROM settings WHERE key = ?", (key,))
    await db.commit()

    return {"status": "ok", "reset_key": key}


settings_router = Router(
    path="/api",
    route_handlers=[get_app_settings, get_about_info, update_settings, reset_setting],
)
