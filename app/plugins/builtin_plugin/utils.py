"""插件工具函数：从 BasePlugin 提取出的通用方法。"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import jinja2
from PIL import Image

if TYPE_CHECKING:
    pass

# 模板环境缓存（按目录）
_template_envs: dict[str, jinja2.Environment] = {}


def normalize_thumbnail(image: Image.Image, size: tuple = (300, 400)) -> Image.Image:
    """标准化缩略图：缩放到指定尺寸，RGBA/P 转 RGB。"""
    image.thumbnail(size)
    if image.mode in ("RGBA", "P"):
        image = image.convert("RGB")
    return image


def render_template(
    template_name: str,
    context: dict,
    template_dir: Path | None = None,
) -> str:
    """渲染 Jinja2 模板。支持按目录缓存多个 Jinja2 环境。"""
    if template_dir is None:
        # 从调用者的代码对象获取插件文件所在目录
        import inspect
        frame = inspect.currentframe()
        if frame and frame.f_back:
            template_dir = Path(frame.f_back.f_code.co_filename).parent
        if template_dir is None:
            raise RuntimeError("Cannot determine template directory")

    dir_key = str(template_dir)
    if dir_key not in _template_envs:
        _template_envs[dir_key] = jinja2.Environment(
            loader=jinja2.FileSystemLoader(dir_key),
            autoescape=jinja2.select_autoescape(["html", "xml"]),
        )
    template = _template_envs[dir_key].get_template(template_name)
    return template.render(**context)


def read_text_with_encoding(file_path: Path) -> tuple[str, str]:
    """智能读取文本文件，自动检测编码。返回 (content, encoding)。"""
    import chardet

    raw_data = file_path.read_bytes()
    detected = chardet.detect(raw_data)
    encoding = detected.get("encoding") if detected else None
    if encoding:
        try:
            return raw_data.decode(encoding), encoding
        except (UnicodeDecodeError, ValueError):
            return raw_data.decode("utf-8", errors="replace"), "utf-8"
    return raw_data.decode("utf-8", errors="replace"), "utf-8"
