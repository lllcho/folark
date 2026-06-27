import json
import logging
from functools import lru_cache
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings

logger = logging.getLogger(__name__)

# DB 中用户自定义的配置覆盖值
_db_overrides: dict = {}


class Settings(BaseSettings):
    DATA_ROOT: Path = Path("./data")  # 数据根目录，所有数据文件都在此下

    # 以下字段由 DATA_ROOT 自动派生，通常无需单独配置
    LIBRARY_ROOT: Path | None = None  # 文档存储目录，默认 DATA_ROOT/library
    PREVIEWS_ROOT: Path | None = None  # 预览文件目录，默认 LIBRARY_ROOT/.previews
    DB_PATH: Path | None = None  # 数据库路径，默认 DATA_ROOT/folark.db
    LOG_DIR: Path | None = None  # 日志目录，默认 DATA_ROOT/logs

    PORT: int = 8890
    LOG_LEVEL: str = "DEBUG"
    MAX_UPLOAD_SIZE: int = 500 * 1024 * 1024  # 500MB，默认值
    MAX_PLAIN_TEXT_BYTES: int = 100 * 1024  # plain_text 字段最大存储限制（100KB）
    TRUNCATION_NOTICE: str = "[原文超出 100KB 存储限制, 仅截取部分内容]"
    IMPORT_DIR_WHITELIST: list[Path] = []

    # ---------- 认证配置 ----------
    AUTH_PASSWORD: str = ""  # 登录密码，为空则不启用认证
    AUTH_SECRET_KEY: str = "folark-local-auth"  # Cookie 签名密钥
    AUTH_COOKIE_NAME: str = "folark_session"  # Cookie 名称
    AUTH_MAX_AGE: int = 7 * 24 * 3600  # Cookie 有效期（7天）

    # ---------- 文件类型分类 ----------
    # 文档类型(办公文档)
    DOCUMENT_EXTENSIONS: set[str] = {
        ".pdf",
        ".docx",
        ".xlsx",
        ".pptx",
    }

    # 电子书类型
    EBOOK_EXTENSIONS: set[str] = {
        ".epub",
        ".mobi",
        ".azw3",
        ".fb2",
    }

    # 纯文本类型(作为整体启用/禁用)
    TEXT_EXTENSIONS: set[str] = {
        # 纯文本/文档
        ".txt",
        ".md",
        # 数据/配置
        ".json",
        ".yaml",
        ".yml",
        ".xml",
        ".toml",
        ".ini",
        ".conf",
        # Web
        ".html",
        ".htm",
        ".css",
        ".js",
        ".ts",
        ".jsx",
        ".tsx",
        # 脚本
        ".sh",
        ".py",
        ".rb",
        # 编程语言
        ".java",
        ".c",
        ".cpp",
        ".go",
        ".rs",
        # 日志/其他
        ".log",
        ".sql",
    }

    # 图片类型(作为整体启用/禁用)
    IMAGE_EXTENSIONS: set[str] = {
        ".jpg",
        ".jpeg",
        ".png",
        ".gif",
        ".bmp",
        ".webp",
        ".tiff",
        ".tif",
        ".ico",
        ".svg",
    }

    # 音频类型
    AUDIO_EXTENSIONS: set[str] = {
        ".mp3",
        ".wav",
        ".flac",
        ".aac",
        ".m4a",
    }

    # 视频类型
    VIDEO_EXTENSIONS: set[str] = {
        ".mp4",
        ".webm",
        ".ogg",
        ".mov",
        ".m4v",
    }

    # 压缩包类型
    ARCHIVE_EXTENSIONS: set[str] = {
        ".zip",
        ".rar",
        ".7z",
        ".tar",
        ".gz",
        ".bz2",
        ".xz",
    }

    # 最终允许的扩展名 = 各分类的并集
    ALLOWED_EXTENSIONS: set[str] = (
        DOCUMENT_EXTENSIONS
        | EBOOK_EXTENSIONS
        | TEXT_EXTENSIONS
        | IMAGE_EXTENSIONS
        | AUDIO_EXTENSIONS
        | VIDEO_EXTENSIONS
        | ARCHIVE_EXTENSIONS
    )

    @model_validator(mode="after")
    def set_derived_paths(self) -> "Settings":
        """从 DATA_ROOT 派生默认路径"""
        if self.LIBRARY_ROOT is None:
            self.LIBRARY_ROOT = self.DATA_ROOT / "library"
        if self.DB_PATH is None:
            self.DB_PATH = self.DATA_ROOT / "folark.db"
        if self.PREVIEWS_ROOT is None:
            self.PREVIEWS_ROOT = self.LIBRARY_ROOT / ".previews"
        if self.LOG_DIR is None:
            self.LOG_DIR = self.DATA_ROOT / "logs"
        return self

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


# 允许前端编辑的配置 key
EDITABLE_KEYS: set[str] = {
    "LOG_LEVEL",
    "MAX_UPLOAD_SIZE",
    "IMPORT_DIR_WHITELIST",
    "DOCUMENT_EXTENSIONS",
    "EBOOK_EXTENSIONS",
    "TEXT_EXTENSIONS",
    "IMAGE_EXTENSIONS",
    "AUDIO_EXTENSIONS",
    "VIDEO_EXTENSIONS",
    "ARCHIVE_EXTENSIONS",
}


def get_category_map(settings: "Settings | None" = None) -> dict[str, set[str]]:
    """返回文件类型分类名到扩展名集合的映射。"""
    s = settings or get_settings()
    return {
        "document": s.DOCUMENT_EXTENSIONS,
        "ebook": s.EBOOK_EXTENSIONS,
        "text": s.TEXT_EXTENSIONS,
        "image": s.IMAGE_EXTENSIONS,
        "video": s.VIDEO_EXTENSIONS,
        "audio": s.AUDIO_EXTENSIONS,
        "archive": s.ARCHIVE_EXTENSIONS,
    }


def resolve_file_path(file_path_str: str, import_method: str) -> Path:
    """将数据库中存储的文件路径解析为绝对路径。

    上传文件（import_method='upload'）存储的是相对路径，
    需要拼接 LIBRARY_ROOT；目录导入的已是绝对路径。
    """
    p = Path(file_path_str)
    if import_method == "upload" and not p.is_absolute():
        return get_settings().LIBRARY_ROOT.resolve() / p
    return p


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    # 叠加 DB 覆盖值（JSON list 转 set）
    for key, value in _db_overrides.items():
        if hasattr(s, key):
            current = getattr(s, key)
            if isinstance(current, set) and isinstance(value, list):
                value = set(value)
            object.__setattr__(s, key, value)
    # 重算 ALLOWED_EXTENSIONS
    object.__setattr__(
        s,
        "ALLOWED_EXTENSIONS",
        (
            s.DOCUMENT_EXTENSIONS
            | s.EBOOK_EXTENSIONS
            | s.TEXT_EXTENSIONS
            | s.IMAGE_EXTENSIONS
            | s.AUDIO_EXTENSIONS
            | s.VIDEO_EXTENSIONS
            | s.ARCHIVE_EXTENSIONS
        ),
    )
    return s


def reload_settings(overrides: dict) -> None:
    """写入 DB 后调用，刷新内存中的配置。"""
    global _db_overrides
    _db_overrides = overrides
    get_settings.cache_clear()


async def load_settings_from_db(db) -> dict:
    """启动时从 DB 加载用户配置并填入 _db_overrides。"""
    async with db.execute("SELECT key, value FROM settings") as cur:
        rows = await cur.fetchall()
    overrides = _parse_db_rows(rows)
    reload_settings(overrides)


def _parse_db_rows(rows) -> dict:
    """解析 DB 中的 settings 行，处理 SQLite JSON 列可能返回原生类型的情况。"""
    overrides = {}
    for key, value in rows:
        if isinstance(value, str):
            try:
                overrides[key] = json.loads(value)
            except (json.JSONDecodeError, TypeError):
                logger.warning("配置值无效 key=%s, 已跳过", key)
        else:
            # SQLite JSON 列可能直接返回 int/float/list/dict
            overrides[key] = value
    return overrides
