"""内置插件 — 合并所有内置任务到一个插件容器中。

各任务的实际实现委托给原子插件模块，BuiltinPlugin 仅作为任务注册容器。
plugin_name + task_name 构成任务的唯一标识。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from app.plugins.builtin_plugin import pdf_plugin
from app.plugins.builtin_plugin import image_plugin
from app.plugins.builtin_plugin import text_plugin
from app.plugins.builtin_plugin import txt_plugin
from app.plugins.builtin_plugin import docx_plugin
from app.plugins.builtin_plugin import epub_plugin
from app.plugins.builtin_plugin import pptx_plugin
from app.plugins.builtin_plugin import xlsx_plugin
from app.plugins.builtin_plugin import audio_plugin
from app.plugins.builtin_plugin import video_plugin
from app.plugins.builtin_plugin import zip_plugin
from app.plugins.core import BasePlugin, ExtractResult, ThumbnailResult, ConvertResult, PreviewResult, TaskHandlerMode, TaskHandlerType, task_handler

if TYPE_CHECKING:
    from app.plugins.core import PluginContext

logger = logging.getLogger(__name__)


class BuiltinPlugin(BasePlugin):
    """内置插件：包含所有内置任务，委托到各子插件函数。"""

    name = "builtin"
    version = "1.0.0"
    default_config = {"thumbnail_quality": 85, "max_pages": 100, "max_size": 10 * 1024 * 1024, "max_pages_per_file": 100, "max_file_size": 10 * 1024 * 1024, "max_image_size": 10 * 1024 * 1024, "max_audio_size": 10 * 1024 * 1024, "max_video_size": 10 * 1024 * 1024, "max_zip_size": 10 * 1024 * 1024, "max_extract_size": 10 * 1024 * 1024, "max_image_pages": 100, "max_pdf_pages": 100, "max_epub_pages": 100, "max_pptx_pages": 100, "max_xlsx_pages": 100}

    # PDF 任务

    @task_handler(handler_name="pdf_extract", handler_type=TaskHandlerType.EXTRACT, source_types=["pdf"],
          handler_mode=TaskHandlerMode.INSTANT, description="提PDF文本内容")
    def pdf_extract(self, ctx: PluginContext) -> ExtractResult | None:
        return pdf_plugin.extract(ctx)

    @task_handler(handler_name="pdf_thumbnail", handler_type=TaskHandlerType.THUMBNAIL, source_types=["pdf"],
          handler_mode=TaskHandlerMode.INSTANT, description="生成PDF首页缩略图")
    def pdf_thumbnail(self, ctx: PluginContext) -> ThumbnailResult | None:
        return pdf_plugin.thumbnail(ctx)

    @task_handler(handler_name="pdf_preview", handler_type=TaskHandlerType.PREVIEW, source_types=["pdf"],
          handler_mode=TaskHandlerMode.ON_DEMAND, description="PDF预览")
    def pdf_preview(self, ctx: PluginContext) -> PreviewResult:
        return pdf_plugin.preview(ctx)

    # Image 任务

    @task_handler(handler_name="image_thumbnail", handler_type=TaskHandlerType.THUMBNAIL, source_types=["image"],
          handler_mode=TaskHandlerMode.INSTANT, description="生成图片缩略图")
    def image_thumbnail(self, ctx: PluginContext) -> ThumbnailResult | None:
        return image_plugin.thumbnail(ctx)

    @task_handler(handler_name="image_preview", handler_type=TaskHandlerType.PREVIEW, source_types=["image"],
          handler_mode=TaskHandlerMode.ON_DEMAND, description="图片在线查看器")
    def image_preview(self, ctx: PluginContext) -> PreviewResult:
        return image_plugin.preview(ctx)

    # Text 任务
    @task_handler(handler_name="text_extract", handler_type=TaskHandlerType.EXTRACT, source_types=["text"],
          handler_mode=TaskHandlerMode.INSTANT, description="提取文本文件内容")
    def text_extract(self, ctx: PluginContext) -> ExtractResult | None:
        return text_plugin.extract(ctx)

    @task_handler(handler_name="text_preview", handler_type=TaskHandlerType.PREVIEW, source_types=["text"],
          handler_mode=TaskHandlerMode.ON_DEMAND, description="文本查看器")
    def text_preview(self, ctx: PluginContext) -> PreviewResult:
        return text_plugin.preview(ctx)

    # TXT 任务

    @task_handler(handler_name="txt_convert_epub", handler_type=TaskHandlerType.CONVERT, source_types=["txt"],
          target_types=["epub"], handler_mode=TaskHandlerMode.ON_DEMAND, description="TXT转EPUB格式")
    def txt_convert_epub(self, ctx: PluginContext) -> ConvertResult | None:
        return txt_plugin.convert(ctx)

    # DOCX 任务

    @task_handler(handler_name="docx_extract", handler_type=TaskHandlerType.EXTRACT, source_types=["docx"],
          handler_mode=TaskHandlerMode.INSTANT, description="提取DOCX文本内容")
    def docx_extract(self, ctx: PluginContext) -> ExtractResult | None:
        return docx_plugin.extract(ctx)

    @task_handler(handler_name="docx_convert_pdf", handler_type=TaskHandlerType.CONVERT, source_types=["docx"],
          target_types=["pdf"], handler_mode=TaskHandlerMode.ON_DEMAND, description="DOCX转PDF")
    def docx_convert_pdf(self, ctx: PluginContext) -> ConvertResult | None:
        return docx_plugin.convert(ctx)

    @task_handler(handler_name="docx_preview", handler_type=TaskHandlerType.PREVIEW, source_types=["docx"],
          handler_mode=TaskHandlerMode.ON_DEMAND, description="DOCX文件在线预览")
    def docx_preview(self, ctx: PluginContext) -> PreviewResult:
        return docx_plugin.preview(ctx)

    # EPUB 任务

    @task_handler(handler_name="epub_extract", handler_type=TaskHandlerType.EXTRACT, source_types=["epub"],
          handler_mode=TaskHandlerMode.INSTANT, description="提取EPUB文本内容")
    def epub_extract(self, ctx: PluginContext) -> ExtractResult | None:
        return epub_plugin.extract(ctx)

    @task_handler(handler_name="epub_thumbnail", handler_type=TaskHandlerType.THUMBNAIL, source_types=["epub"],
          handler_mode=TaskHandlerMode.INSTANT, description="提取EPUB电子书封面")
    def epub_thumbnail(self, ctx: PluginContext) -> ThumbnailResult | None:
        return epub_plugin.thumbnail(ctx)

    @task_handler(handler_name="epub_preview", handler_type=TaskHandlerType.PREVIEW, source_types=["epub"],
          handler_mode=TaskHandlerMode.ON_DEMAND, description="EPUB电子书阅读器")
    def epub_preview(self, ctx: PluginContext) -> PreviewResult:
        return epub_plugin.preview(ctx)

    # PPTX 任务

    @task_handler(handler_name="pptx_extract", handler_type=TaskHandlerType.EXTRACT, source_types=["pptx"],
          handler_mode=TaskHandlerMode.INSTANT, description="提取PPTX文本内容")
    def pptx_extract(self, ctx: PluginContext) -> ExtractResult | None:
        return pptx_plugin.extract(ctx)

    @task_handler(handler_name="pptx_convert_pdf", handler_type=TaskHandlerType.CONVERT, source_types=["pptx"],
          target_types=["pdf"], handler_mode=TaskHandlerMode.ON_DEMAND, description="PPTX转PDF")
    def pptx_convert_pdf(self, ctx: PluginContext) -> ConvertResult | None:
        return pptx_plugin.convert(ctx)

    @task_handler(handler_name="pptx_preview", handler_type=TaskHandlerType.PREVIEW, source_types=["pptx"],
          handler_mode=TaskHandlerMode.ON_DEMAND, description="PPTX在线预览")
    def pptx_preview(self, ctx: PluginContext) -> PreviewResult:
        return pptx_plugin.preview(ctx)

    # XLSX 任务

    @task_handler(handler_name="xlsx_extract", handler_type=TaskHandlerType.EXTRACT, source_types=["xlsx"],
          handler_mode=TaskHandlerMode.INSTANT, description="提取Excel表格内容")
    def xlsx_extract(self, ctx: PluginContext) -> ExtractResult | None:
        return xlsx_plugin.extract(ctx)

    @task_handler(handler_name="xlsx_preview", handler_type=TaskHandlerType.PREVIEW, source_types=["xlsx"],
          handler_mode=TaskHandlerMode.ON_DEMAND, description="Excel在线预览")
    def xlsx_preview(self, ctx: PluginContext) -> PreviewResult:
        return xlsx_plugin.preview(ctx)

    # Audio 任务

    @task_handler(handler_name="audio_preview", handler_type=TaskHandlerType.PREVIEW, source_types=["audio"],
          handler_mode=TaskHandlerMode.ON_DEMAND, description="音频播放器")
    def audio_preview(self, ctx: PluginContext) -> PreviewResult:
        return audio_plugin.preview(ctx)

    # Video 任务

    @task_handler(handler_name="video_preview", handler_type=TaskHandlerType.PREVIEW, source_types=["video"],
          handler_mode=TaskHandlerMode.ON_DEMAND, description="视频播放器")
    def video_preview(self, ctx: PluginContext) -> PreviewResult:
        return video_plugin.preview(ctx)

    # Archive 任务

    @task_handler(handler_name="archive_extract", handler_type=TaskHandlerType.EXTRACT, source_types=["archive"],
          handler_mode=TaskHandlerMode.INSTANT, description="提取压缩包目录树结构")
    def archive_extract(self, ctx: PluginContext) -> ExtractResult | None:
        return zip_plugin.extract(ctx)

    @task_handler(handler_name="archive_preview", handler_type=TaskHandlerType.PREVIEW, source_types=["archive"],
          handler_mode=TaskHandlerMode.ON_DEMAND, description="压缩包内容预览")
    def archive_preview(self, ctx: PluginContext) -> PreviewResult:
        return zip_plugin.preview(ctx)
