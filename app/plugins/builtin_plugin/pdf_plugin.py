"""PDF 文件处理实现。"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.plugins.builtin_plugin.utils import normalize_thumbnail
from app.plugins.core import PreviewResult

if TYPE_CHECKING:
    from PIL import Image as PILImage

    from app.plugins.core import PluginContext

logger = logging.getLogger(__name__)


def extract(ctx: PluginContext) -> str | None:
    """从 PDF 文件提取文本。"""
    try:
        import fitz  # pymupdf

        doc = fitz.open(ctx.file_path)
        text_parts = []
        for page in doc:
            text_parts.append(page.get_text())
        doc.close()

        text = "\n".join(text_parts).strip()
        if not text:
            return None
        return text
    except Exception as e:
        logger.warning("PDF 文本提取失败 %s: %s", ctx.file_path, e)
        return None


def thumbnail(ctx: PluginContext) -> PILImage.Image | None:
    """从 PDF 第一页生成缩略图，返回 PIL Image 对象。"""
    try:
        import io

        import pymupdf
        from PIL import Image

        doc = pymupdf.open(ctx.file_path)
        if len(doc) == 0:
            doc.close()
            return None

        page = doc[0]
        pix = page.get_pixmap()
        doc.close()

        img = Image.open(io.BytesIO(pix.tobytes("png")))
        return normalize_thumbnail(img)
    except Exception as e:
        logger.warning("PDF 缩略图生成失败 %s: %s", ctx.file_path, e)
        return None


def preview(ctx: PluginContext) -> PreviewResult:
    """PDF 使用浏览器直接渲染。"""
    return PreviewResult.from_file(
        path=ctx.file_path, media_type="application/pdf"
    )
