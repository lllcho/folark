"""EPUB 文件处理实现。"""

from __future__ import annotations

import logging

from app.plugins.builtin_plugin.utils import normalize_thumbnail, render_template
from app.plugins.core import PluginContext, PreviewResult

logger = logging.getLogger(__name__)


# ── extract ──────────────────────────────────────────────
def extract(ctx: PluginContext) -> str | None:
    try:
        import ebooklib
        from ebooklib import epub
        from bs4 import BeautifulSoup

        book = epub.read_epub(str(ctx.file_path), options={"ignore_ncx": True})
        texts: list[str] = []
        for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
            soup = BeautifulSoup(item.get_content(), "html.parser")
            text = soup.get_text(separator="\n", strip=True)
            if text:
                texts.append(text)
        return "\n".join(texts) if texts else None
    except Exception as e:
        logger.warning("EPUB 文本提取失败 %s: %s", ctx.file_path, e)
        return None


# ── thumbnail ────────────────────────────────────────────
def thumbnail(ctx: PluginContext):
    try:
        import io

        import ebooklib
        from ebooklib import epub
        from PIL import Image

        book = epub.read_epub(str(ctx.file_path), options={"ignore_ncx": True})

        cover_item = None

        # 1) 尝试从 OPF 元数据获取 cover id
        cover_meta = book.get_metadata("OPF", "cover")
        if cover_meta:
            cover_id = cover_meta[0][1].get("content", "") if cover_meta[0][1] else ""
            if cover_id:
                cover_item = book.get_item_with_id(cover_id)

        # 2) 遍历图片 item，查找文件名包含 "cover" 的
        if cover_item is None:
            for item in book.get_items_of_type(ebooklib.ITEM_IMAGE):
                if "cover" in item.get_name().lower():
                    cover_item = item
                    break

        # 3) fallback: 取第一个图片 item
        if cover_item is None:
            for item in book.get_items_of_type(ebooklib.ITEM_IMAGE):
                cover_item = item
                break

        if cover_item is None:
            return None

        img = Image.open(io.BytesIO(cover_item.get_content()))
        return normalize_thumbnail(img)
    except Exception as e:
        logger.warning("EPUB 缩略图生成失败 %s: %s", ctx.file_path, e)
        return None


# ── preview ──────────────────────────────────────────────
def preview(ctx: PluginContext) -> PreviewResult:
    html = render_template("epub_preview.html", {
        "file_name": ctx.file_name,
        "title": ctx.title or ctx.file_name,
        "epub_url": ctx.file_url,
    })
    return PreviewResult.from_html(html)
