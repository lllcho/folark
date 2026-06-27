"""纯文本文件处理实现。"""

from __future__ import annotations

import logging

from app.plugins.builtin_plugin.utils import read_text_with_encoding, render_template
from app.plugins.core import PluginContext, PreviewResult

logger = logging.getLogger(__name__)


def extract(ctx: PluginContext) -> str | None:
    try:
        content, _ = read_text_with_encoding(ctx.file_path)
        return content
    except Exception as e:
        logger.warning("文本文件提取失败 %s: %s", ctx.file_path, e)
        return None


def preview(ctx: PluginContext) -> PreviewResult:
    file_content, _ = read_text_with_encoding(ctx.file_path)

    html = render_template(
        "text_preview.html",
        {
            "file_name": ctx.file_name,
            "content": file_content,
            "file_type": f".{ctx.file_type}",
            "title": ctx.title or ctx.file_name,
        },
    )
    return PreviewResult.from_html(html)
