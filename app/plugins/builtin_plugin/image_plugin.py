"""Image 文件处理实现。"""

from __future__ import annotations

import logging
import mimetypes
from typing import TYPE_CHECKING

from app.plugins.core import PreviewResult

if TYPE_CHECKING:
    from PIL import Image as PILImage

    from app.plugins.core import PluginContext

logger = logging.getLogger(__name__)

# 支持缩略图生成的图片类型（Pillow 可处理，SVG 除外）
_THUMBNAIL_IMAGE_TYPES: set[str] = {
    "jpg", "jpeg", "png", "gif", "bmp", "webp", "tiff", "tif", "ico",
}


def thumbnail(ctx: PluginContext) -> PILImage.Image | None:
    """从图片文件生成缩略图，返回 PIL Image 对象。"""
    # SVG 不支持缩略图
    if ctx.file_type == "svg":
        return None

    if ctx.file_type not in _THUMBNAIL_IMAGE_TYPES:
        return None

    try:
        from PIL import Image

        img = Image.open(ctx.file_path)
        img.thumbnail((300, 400))
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        return img
    except Exception as e:
        logger.warning("图片缩略图生成失败 %s: %s", ctx.file_path, e)
        return None


def preview(ctx: PluginContext) -> PreviewResult:
    """图片直接浏览器显示。"""
    media_type = mimetypes.guess_type(f"file.{ctx.file_type}")[0] or f"image/{ctx.file_type}"
    return PreviewResult.from_file(
        path=ctx.file_path,
        media_type=media_type,
    )
