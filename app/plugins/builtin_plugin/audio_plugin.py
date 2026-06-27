"""Audio 文件处理实现。"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.plugins.builtin_plugin.utils import render_template
from app.plugins.core import PreviewResult

if TYPE_CHECKING:
    from app.plugins.core import PluginContext

logger = logging.getLogger(__name__)

_AUDIO_MIME_MAP = {
    "mp3": "audio/mpeg",
    "wav": "audio/wav",
    "flac": "audio/flac",
    "aac": "audio/aac",
    "ogg": "audio/ogg",
    "m4a": "audio/mp4",
}


def preview(ctx: PluginContext) -> PreviewResult:
    """使用模板渲染音频预览页面。"""
    html = render_template("audio_preview.html", {
        "file_name": ctx.file_name,
        "title": ctx.title or ctx.file_name,
        "audio_url": ctx.file_url,
        "audio_type": _AUDIO_MIME_MAP.get(ctx.file_type, "audio/mpeg"),
    })
    return PreviewResult.from_html(html)
