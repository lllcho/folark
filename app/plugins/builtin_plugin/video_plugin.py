"""Video 文件处理实现。"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.plugins.builtin_plugin.utils import render_template
from app.plugins.core import PreviewResult

if TYPE_CHECKING:
    from app.plugins.core import PluginContext

logger = logging.getLogger(__name__)

_VIDEO_MIME_MAP = {
    "mp4": "video/mp4",
    "webm": "video/webm",
    "ogg": "video/ogg",
    "mov": "video/mp4",
    "m4v": "video/mp4",
}


def preview(ctx: PluginContext) -> PreviewResult:
    """使用模板渲染视频预览页面。"""
    html = render_template(
        "video_preview.html",
        {
            "file_name": ctx.file_name,
            "title": ctx.title or ctx.file_name,
            "video_url": ctx.file_url,
            "video_type": _VIDEO_MIME_MAP.get(ctx.file_type, "video/mp4"),
        },
    )
    return PreviewResult.from_html(html)
