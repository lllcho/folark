"""插件核心框架：定义任务类型、装饰器、上下文数据类及任务结果自持久化。"""

from __future__ import annotations
from typing import Any
from dataclasses import dataclass
from enum import Enum
from functools import wraps
from pathlib import Path
from typing import Callable, TypeVar

from app.config import Settings


# ── TaskHandlerType 枚举 ─────────────────────────────────────────
class TaskHandlerType(str, Enum):
    """任务类型枚举，同时也是字符串。"""

    EXTRACT = "extract"
    THUMBNAIL = "thumbnail"
    SUMMARIZE = "summarize"
    CONVERT = "convert"
    PREVIEW = "preview"

    def __str__(self) -> str:
        return self.value


# ── TaskHandlerMode 枚举 ─────────────────────────────────────────
class TaskHandlerMode(str, Enum):
    """任务执行模式。"""

    INSTANT = "instant"
    BACKGROUND = "background"
    ON_DEMAND = "on_demand"

    def __str__(self) -> str:
        return self.value


# ── 任务类型常量 ──────────────────────────────────────────
PIPELINE_HANDLER_TYPES = {TaskHandlerType.EXTRACT, TaskHandlerType.THUMBNAIL, TaskHandlerType.SUMMARIZE}
ON_DEMAND_HANDLER_TYPES = {TaskHandlerType.CONVERT, TaskHandlerType.PREVIEW}


# ── TaskHandlerInfo 数据类 ───────────────────────────────────────
@dataclass(frozen=True)
class TaskHandlerInfo:
    """任务处理器元数据描述"""

    handler_name: str
    handler_type: TaskHandlerType
    source_types: list[str]
    target_types: list[str] | None = None
    handler_mode: TaskHandlerMode = TaskHandlerMode.INSTANT
    description: str = ""

# ── TaskHandler 数据类 ─────────────────────────────────────
@dataclass
class TaskHandler:
    """任务处理器封装"""

    plugin: BasePlugin
    method: Callable[..., Any]  # 绑定的方法引用
    info: TaskHandlerInfo
    enabled: bool = True

# ── @task_handler 装饰器 ──────────────────────────────────
F = TypeVar("F", bound=Callable)


def task_handler(
    handler_name: str,
    handler_type: TaskHandlerType,
    source_types: list[str],
    target_types: list[str] | None = None,
    handler_mode: TaskHandlerMode = TaskHandlerMode.INSTANT,
    description: str = "",
) -> Callable[[F], F]:
    """标记方法为任务处理器，将 TaskHandlerInfo 绑定到方法的 _task_handler_info 属性。

    同时自动将原始返回值包装为对应的 Result 类型：
      - EXTRACT: str -> ExtractResult
      - THUMBNAIL: PILImage -> ThumbnailResult
      - CONVERT: bytes -> ConvertResult
      - PREVIEW: 不转换（子模块已返回 PreviewResult）
    若返回值已是 Result 类型或为 None，则原样返回。
    """
    info = TaskHandlerInfo(
        handler_name=handler_name,
        handler_type=handler_type,
        source_types=source_types,
        target_types=target_types,
        handler_mode=handler_mode,
        description=description,
    )

    def decorator(func: F) -> F:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            result = func(*args, **kwargs)
            if result is None or isinstance(result, (ExtractResult, ThumbnailResult, SummarizeResult, ConvertResult, PreviewResult)):
                return result
            if handler_type == TaskHandlerType.EXTRACT:
                return ExtractResult.from_text(result)
            if handler_type == TaskHandlerType.THUMBNAIL:
                return ThumbnailResult.from_image(result)
            if handler_type == TaskHandlerType.CONVERT:
                ctx = args[1] if len(args) > 1 else kwargs.get("ctx")
                return ConvertResult.from_bytes(result, ctx.target_type if ctx else "")
            return result

        wrapper._task_handler_info = info  # type: ignore[attr-defined]
        return wrapper  # type: ignore[return-value]

    return decorator


# ── file-type 工具函数 ──────────────────────────────────────
def get_file_type_categories() -> dict[str, set[str]]:
    """从 Settings 动态生成 file_type 类别映射（去掉点号）。"""
    from app.config import get_settings

    s = get_settings()
    return {
        "document": {e.lstrip(".") for e in s.DOCUMENT_EXTENSIONS},
        "ebook": {e.lstrip(".") for e in s.EBOOK_EXTENSIONS},
        "text": {e.lstrip(".") for e in s.TEXT_EXTENSIONS},
        "image": {e.lstrip(".") for e in s.IMAGE_EXTENSIONS},
        "video": {e.lstrip(".") for e in s.VIDEO_EXTENSIONS},
        "audio": {e.lstrip(".") for e in s.AUDIO_EXTENSIONS},
        "archive": {e.lstrip(".") for e in s.ARCHIVE_EXTENSIONS},
    }


def expand_source_types(source_types: list[str]) -> set[str]:
    """将类别 type 展开为具体 file_type 集合，如 ``['image'] -> {'jpg','png',...}``。"""
    cats = get_file_type_categories()
    result: set[str] = set()
    for t in source_types:
        if t in cats:
            result |= cats[t]
        else:
            result.add(t)
    return result


# ── 数据类 ──────────────────────────────────────────────────
@dataclass
class PluginContext:
    """传递给插件各任务方法的上下文对象。"""

    id: int
    uuid: str
    file_name: str
    file_path: Path  # 文件本地路径
    file_type: str  # 不带点，如 "pdf"
    file_size: int | None
    title: str | None
    authors: str | None
    summary: str | None
    meta_data: str | None
    thumbnail_path: str | None
    plain_text: str | None
    settings: Settings
    file_url: str | None = None  # 文件 URL
    target_type: str | None = None  # convert 任务的目标类型


@dataclass
class ExtractResult:
    """extract 任务的输出类型。

    持久化：INSERT OR REPLACE INTO document_texts
      plain_text → document_texts.plain_text
      word_count → document_texts.word_count
    """

    plain_text: str

    @property
    def word_count(self) -> int:
        """计算词数（中英文混合）。"""
        import re
        return len(re.findall(r'[\u4e00-\u9fff\u3400-\u4dbf]|\b\w+\b', self.plain_text))

    @classmethod
    def from_text(cls, text: str) -> "ExtractResult":
        """从纯文本创建提取结果。"""
        return cls(plain_text=text)

    async def persist(self, db: Any, document_id: int, **kwargs: Any) -> dict[str, Any]:
        """将提取结果持久化到 document_texts 表。

        若 plain_text 超过 MAX_PLAIN_TEXT_BYTES 限制，则截断并追加通知。
        word_count 始终基于原始完整文本计算，保证统计准确性。
        """
        # 先基于原文计算词数
        original_word_count = self.word_count

        # 按 UTF-8 字节长度截断
        settings: Settings | None = kwargs.get("settings")
        stored_text = self.plain_text
        if settings and len(self.plain_text.encode("utf-8")) > settings.MAX_PLAIN_TEXT_BYTES:
            max_bytes = settings.MAX_PLAIN_TEXT_BYTES
            encoded = self.plain_text.encode("utf-8")
            stored_text = encoded[:max_bytes].decode("utf-8", errors="ignore")
            stored_text = settings.TRUNCATION_NOTICE+'\n'+stored_text

        await db.execute(
            "INSERT OR REPLACE INTO document_texts (document_id, plain_text, word_count) VALUES (?, ?, ?)",
            (document_id, stored_text, original_word_count),
        )
        await db.commit()
        return {"plain_text": stored_text, "word_count": original_word_count}


@dataclass
class ThumbnailResult:
    """thumbnail 任务的输出类型。

    持久化：
      1. 图片保存为 .thumbnails/{uuid}.jpg 文件
      2. 相对路径 UPDATE 到 documents.thumbnail_path
    """

    image: Any  # PILImage.Image，避免核心层依赖 PIL
    format: str = "JPEG"
    quality: int = 85

    @classmethod
    def from_image(cls, image: Any, *, format: str = "JPEG", quality: int = 85) -> "ThumbnailResult":
        """从 PIL Image 创建缩略图结果。"""
        return cls(image=image, format=format, quality=quality)

    async def persist(self, db: Any, document_id: int, **kwargs: Any) -> dict[str, Any]:
        """保存缩略图文件并将路径持久化到 documents 表。"""
        uuid: str = kwargs["uuid"]
        settings: Settings = kwargs["settings"]

        image = self.image
        if image.mode in ("RGBA", "P"):
            image = image.convert("RGB")

        thumbnails_dir = settings.LIBRARY_ROOT / ".thumbnails"
        thumbnails_dir.mkdir(parents=True, exist_ok=True)
        output_path = thumbnails_dir / f"{uuid}.jpg"
        image.save(output_path, self.format, quality=self.quality)

        rel_path = f".thumbnails/{uuid}.jpg"
        await db.execute(
            "UPDATE documents SET thumbnail_path=? WHERE id=?",
            (rel_path, document_id),
        )
        await db.commit()
        return {"thumbnail_path": rel_path}


@dataclass
class SummarizeResult:
    """summarize 任务的输出类型。

    持久化：UPDATE documents SET summary=? WHERE id=?
    """

    summary: str

    @classmethod
    def from_summary(cls, summary: str) -> "SummarizeResult":
        """从摘要文本创建结果。"""
        return cls(summary=summary)

    async def persist(self, db: Any, document_id: int, **kwargs: Any) -> dict[str, Any]:
        """将摘要结果持久化到 documents 表。"""
        await db.execute(
            "UPDATE documents SET summary=? WHERE id=?",
            (self.summary, document_id),
        )
        await db.commit()
        return {"summary": self.summary}


@dataclass
class ConvertResult:
    """convert 任务的输出类型。

    按需返回，不持久化到数据库。结果直接返回给调用方，
    由上层决定如何使用（如保存为临时文件用于预览）。
    """

    content: bytes
    target_type: str

    @classmethod
    def from_bytes(cls, content: bytes, target_type: str) -> "ConvertResult":
        """从字节数据创建转换结果。"""
        return cls(content=content, target_type=target_type)


@dataclass
class PreviewResult:
    """preview 任务的输出类型。

    按需返回，不持久化到数据库。区分 HTML 字符串与文件路径两种形式。
    """

    kind: str  # "html" | "file"
    html: str | None = None  # kind="html" 时
    file_path: Path | None = None  # kind="file" 时
    media_type: str | None = None  # kind="file" 时的 MIME type

    @classmethod
    def from_html(cls, content: str) -> "PreviewResult":
        """创建 HTML 类型的预览结果。"""
        return cls(kind="html", html=content)

    @classmethod
    def from_file(cls, path: Path, media_type: str | None = None) -> "PreviewResult":
        """创建文件类型的预览结果。"""
        return cls(kind="file", file_path=path, media_type=media_type)

    def is_html(self) -> bool:
        """判断是否为 HTML 类型。"""
        return self.kind == "html" and self.html is not None

    def is_file(self) -> bool:
        """判断是否为文件类型。"""
        return self.kind == "file" and self.file_path is not None


# 所有结果类型的联合
TaskResult = ExtractResult | ThumbnailResult | SummarizeResult | ConvertResult | PreviewResult


async def persist_task_result(
    handler_type: TaskHandlerType,
    result: TaskResult | None,
    db: Any,
    document_id: int,
    **kwargs: Any,
) -> dict[str, Any]:
    """根据任务类型自动持久化结果。

    不需要持久化的类型（CONVERT/PREVIEW）返回 {"status": "skipped"}。
    """
    if result is None:
        return {"status": "no_result"}
    if handler_type not in PIPELINE_HANDLER_TYPES:
        return {"status": "skipped"}
    values = await result.persist(db, document_id, **kwargs)
    return {"status": "success", **values}


# ── BasePlugin 基类 ───────────────────────────────────────
class BasePlugin:
    """插件基类。子类必须定义 name: str 和 version: str。"""

    name: str = ""
    version: str = ""
    plugin_type: str = "builtin"  # 'builtin' | 'community'，由加载方设置
    enabled: bool = True
    default_config: dict = {}  # 插件开发者定义的默认配置值（子类覆盖）

    def __init__(self) -> None:
        # 运行时实际配置 = default_config + DB 用户覆盖
        self.config: dict = {**self.default_config}

    def get_config(self, key: str, default: Any = None) -> Any:
        """获取配置值，优先 config，fallback 到 default_config。"""
        return self.config.get(key, self.default_config.get(key, default))

    def update_config(self, overrides: dict) -> None:
        """用用户覆盖值更新运行时配置（合并到 default_config 基础上）。"""
        self.config = {**self.default_config, **overrides}
