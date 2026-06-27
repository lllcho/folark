"""压缩包文件处理实现。"""

from __future__ import annotations

import logging
import tarfile
import zipfile
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

import py7zr
import rarfile

from app.plugins.builtin_plugin.utils import render_template
from app.plugins.core import PreviewResult

if TYPE_CHECKING:
    from app.plugins.core import PluginContext

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 工具函数：从文件名列表构建目录树并输出文本
# ---------------------------------------------------------------------------

def _build_tree(names: list[str]) -> dict:
    """将路径列表构建为嵌套字典树。"""
    root: dict = {}
    for name in sorted(names):
        parts = PurePosixPath(name).parts
        node = root
        for part in parts:
            node = node.setdefault(part, {})
    return root


def _render_tree_text(tree: dict, prefix: str = "", is_last: bool = True) -> list[str]:
    """将嵌套字典树渲染为带缩进线的文本行列表。"""
    lines: list[str] = []
    items = list(tree.items())
    for i, (name, subtree) in enumerate(items):
        last = (i == len(items) - 1)
        connector = "└── " if last else "├── "
        lines.append(f"{prefix}{connector}{name}")
        extension = "    " if last else "│   "
        lines.extend(_render_tree_text(subtree, prefix + extension, last))
    return lines


def _extract_zip_names(file_path) -> list[str]:
    """从 ZIP 文件提取文件名列表。"""
    with zipfile.ZipFile(file_path, "r") as zf:
        return [
            info.filename
            for info in zf.infolist()
            if not info.filename.startswith("__MACOSX")
        ]


def _extract_tar_names(file_path) -> list[str]:
    """从 tar/tar.gz/tar.bz2/tar.xz 文件提取文件名列表。"""
    with tarfile.open(file_path, "r:*") as tf:
        return [m.name for m in tf.getmembers()]


def _extract_7z_names(file_path) -> list[str]:
    """从 7z 文件提取文件名列表。"""
    with py7zr.SevenZipFile(file_path, mode="r") as sz:
        return sz.getnames()


def _extract_rar_names(file_path) -> list[str]:
    """从 RAR 文件提取文件名列表。"""
    with rarfile.RarFile(file_path, "r") as rf:
        return rf.namelist()


def _get_archive_entries(file_path, file_type: str) -> list[str]:
    """根据文件类型获取压缩包内文件名列表。"""
    if file_type == "zip":
        return _extract_zip_names(file_path)
    elif file_type in ("tar", "gz", "bz2", "xz"):
        return _extract_tar_names(file_path)
    elif file_type == "7z":
        return _extract_7z_names(file_path)
    elif file_type == "rar":
        return _extract_rar_names(file_path)
    else:
        # 未知格式：依次尝试 zip → tar → 7z → rar
        if zipfile.is_zipfile(str(file_path)):
            return _extract_zip_names(file_path)
        try:
            return _extract_tar_names(file_path)
        except Exception:
            pass
        try:
            return _extract_7z_names(file_path)
        except Exception:
            pass
        try:
            return _extract_rar_names(file_path)
        except Exception:
            raise ValueError(f"无法识别的压缩包格式: {file_type}")


def _entries_to_tree_text(entries: list[str]) -> str:
    """将文件名列表转换为目录树文本。"""
    # 过滤空字符串和仅为目录的条目末尾斜杠
    cleaned: list[str] = []
    for e in entries:
        e = e.strip("/")
        if e:
            cleaned.append(e)

    tree = _build_tree(cleaned)
    lines = _render_tree_text(tree)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 插件函数
# ---------------------------------------------------------------------------

def extract(ctx: PluginContext) -> str | None:
    """提取压缩包内的文件列表，返回树形目录结构文本。"""
    try:
        entries = _get_archive_entries(ctx.file_path, ctx.file_type)
        if not entries:
            return None
        return '\n'.join(entries)
    except Exception as e:
        logger.warning("压缩包目录提取失败 %s: %s", ctx.file_path, e)
        return None


def preview(ctx: PluginContext) -> PreviewResult:
    """预览压缩包内的文件目录树结构。"""
    # 从 extract 结果（plain_text）获取文件列表
    raw_entries = []
    if ctx.plain_text:
        raw_entries = [line.strip() for line in ctx.plain_text.split("\n") if line.strip()]

    # 先用原始条目统计文件和目录数量（保留尾部斜杠信息）
    file_count = 0
    dir_count = 0
    for e in raw_entries:
        if e.endswith("/"):
            dir_count += 1
        else:
            file_count += 1

    # 清理后用于构建目录树
    entries = [e.strip("/") for e in raw_entries if e.strip("/")]

    if not entries:
        tree_text = "(空压缩包)"
    else:
        tree_text = _entries_to_tree_text(entries)

    html = render_template("archive_preview.html", {
        "file_name": ctx.file_name,
        "title": ctx.title or ctx.file_name,
        "tree_text": tree_text,
        "file_count": file_count,
        "dir_count": dir_count,
    })
    return PreviewResult.from_html(html)
