"""TXT 文件处理实现 — 转换为 EPUB。"""

from __future__ import annotations

import html as html_mod
import logging
import re
from pathlib import Path
from uuid import uuid4

from app.plugins.builtin_plugin.utils import read_text_with_encoding
from app.plugins.core import PluginContext

logger = logging.getLogger(__name__)


def convert(ctx: PluginContext) -> bytes | None:
    """将 TXT 文件转换为 EPUB 格式（同步方法）。"""
    import io

    from ebooklib import epub

    try:
        content, _ = read_text_with_encoding(ctx.file_path)

        # 避免完全空内容导致空章节
        if not content.strip():
            content = " "

        # 创建 EPUB 书籍
        book = epub.EpubBook()

        # 设置元数据
        book_id = str(uuid4())
        book.set_identifier(book_id)
        book.set_title(ctx.title or ctx.file_path.stem)
        book.set_language("zh")

        if ctx.authors:
            book.add_author(ctx.authors)
        else:
            book.add_author("Unknown")

        # 添加 CSS 样式
        style = """
            @namespace epub "http://www.idpf.org/2007/ops";
            body {
                font-family: "PingFang SC", "Microsoft YaHei", sans-serif;
                line-height: 1.8;
                margin: 2em;
                text-align: justify;
            }
            h1 {
                text-align: center;
                margin: 2em 0;
                font-size: 1.5em;
            }
            p {
                text-indent: 2em;
                margin: 0.5em 0;
            }
        """
        nav_css = epub.EpubItem(
            uid="style_nav",
            file_name="style/default.css",
            media_type="text/css",
            content=style,
        )
        book.add_item(nav_css)

        # 将 TXT 内容分章节
        chapters = _split_into_chapters(content)
        epub_chapters = []

        for i, (chapter_title, chapter_content) in enumerate(chapters):
            safe_title = chapter_title or f"第{i + 1}章"

            # 创建章节 HTML
            html_content = _create_chapter_html(safe_title, chapter_content)

            # 创建 EPUB 章节
            chapter = epub.EpubHtml(
                title=safe_title,
                file_name=f"chapter_{i + 1}.xhtml",
                lang="zh",
            )
            chapter.content = html_content
            chapter.add_item(nav_css)

            book.add_item(chapter)
            epub_chapters.append(chapter)

        # 添加目录
        book.toc = tuple(epub_chapters)

        # 添加导航文件
        book.add_item(epub.EpubNcx())
        book.add_item(epub.EpubNav())

        # 设置阅读顺序
        book.spine = epub_chapters + ["nav"]

        # 生成 EPUB 字节数据
        epub_buffer = io.BytesIO()
        epub.write_epub(epub_buffer, book, {})
        return epub_buffer.getvalue()
    except Exception as e:
        logger.warning("TXT 转 EPUB 失败 %s: %s", ctx.file_path, e)
        return None


def _split_into_chapters(content: str) -> list[tuple[str, str]]:
    """将 TXT 内容分割为章节。

    支持常见中文小说章节、卷标题、特殊章节名、英文 Chapter/Part，
    以及部分脏数据格式（如"1、标题""001 标题""第二 章标题"）。

    Returns:
        [(章节标题, 章节内容), ...]
    """
    normalized = content.replace("\r\n", "\n").replace("\r", "\n")

    cn_num = r"[一二三四五六七八九十百千万零两〇\d]+"
    en_num = r"[A-Za-z0-9IVXLCMivxlcm]+"

    chapter_pattern = re.compile(
        rf"""
        ^[ \t\u3000]*
        (?:
            # 1) 中文主章节：
            [\[【(（]?\s*
            第\s*{cn_num}\s*[章节回卷篇集部册]
            (?:\s*第\s*{cn_num}\s*节)?
            \s*[\]】)）]?
            (?:\s*[-—:：·.、]\s*|\s+)?
            [^\n]{{0,60}}?

            |

            # 2) 卷/部/篇标题：
            [\[【(（]?\s*
            (?:
                卷\s*{cn_num} |
                {cn_num}\s*卷 |
                第\s*{cn_num}\s*卷 |
                第\s*{cn_num}\s*部 |
                第\s*{cn_num}\s*篇
            )
            \s*[\]】)）]?
            (?:\s*[-—:：·.、]\s*|\s+)?
            [^\n]{{0,60}}?

            |

            # 3) 特殊章节名：
            [\[【(（]?\s*
            (?:
                序章 | 序言 | 前言 | 引言 | 楔子 | 正文 |
                尾声 | 后记 | 完本感言 |
                番外(?:\s*{cn_num})? |
                终章 | 终卷 | 大结局 | 结局
            )
            \s*[\]】)）]?
            (?:\s*[-—:：·.、]\s*|\s+)?
            [^\n]{{0,60}}?

            |

            # 4) 英文章节：
            (?:
                Chapter|CHAPTER|chapter|
                Part|PART|part
            )
            \s+{en_num}
            (?:\s*[-—:：.]\s*|\s+)?
            [^\n]{{0,60}}?

            |

            # 5) 英文特殊章节：
            Prologue|PROLOGUE|prologue|Epilogue|EPILOGUE|epilogue

            |

            # 6) Markdown 标题
            \#{{1,3}}\s+.+

            |

            # 7) 数字型脏数据章节：
            (?:
                [\[【(（]?\s*
                \d{{1,4}}
                \s*[\]】)）]?
                (?:
                    \s*[-—:：·.、,，]\s* |
                    \s+
                )
                [^\n]{{1,60}}
            )

            |

            # 8) 纯数字短标题：
            (?:
                \d{{1,4}}
                (?:
                    \s+ [^\n]{{1,20}}
                )?
            )

        )
        [ \t\u3000]*$
        """,
        re.MULTILINE | re.VERBOSE,
    )

    matches = list(chapter_pattern.finditer(normalized))

    if not matches:
        paragraphs = re.split(r"\n\s*\n", normalized)
        paragraphs = [p.strip() for p in paragraphs if p.strip()]

        if paragraphs:
            return [("正文", "\n\n".join(paragraphs))]
        return [("正文", normalized)]

    # 启发式过滤，尽量减少误判
    filtered_matches = []
    for m in matches:
        line = m.group(0).strip()
        if _looks_like_chapter_title(line):
            filtered_matches.append(m)

    if not filtered_matches:
        paragraphs = re.split(r"\n\s*\n", normalized)
        paragraphs = [p.strip() for p in paragraphs if p.strip()]

        if paragraphs:
            return [("正文", "\n\n".join(paragraphs))]
        return [("正文", normalized)]

    chapters = []

    # 第一章之前内容作为前言
    if filtered_matches[0].start() > 0:
        preface = normalized[: filtered_matches[0].start()].strip()
        if preface:
            chapters.append(("前言", preface))

    for i, match in enumerate(filtered_matches):
        title = match.group(0).strip()
        start = match.end()
        end = filtered_matches[i + 1].start() if i + 1 < len(filtered_matches) else len(normalized)
        chapter_content = normalized[start:end].strip()
        chapters.append((title, chapter_content))

    if not chapters:
        return [("正文", normalized)]

    chapters = _merge_consecutive_titles_as_toc(chapters)
    return chapters


def _looks_like_chapter_title(line: str) -> bool:
    """启发式判断某一行是否像章节标题。"""
    s = line.strip()
    if not s:
        return False

    # 太长通常不是标题
    if len(s) > 70:
        return False

    # 很像正文的结束标点，通常不是标题
    if s.endswith(("。", "！", "？", "；", ";", ".", "\u201d", '"', "'")):
        return False

    # 纯数字过长不算标题
    if re.fullmatch(r"\d{5,}", s):
        return False

    # 中文主章节/卷/回/篇/部/集
    if re.fullmatch(
        r"[\[【(（]?\s*第\s*[一二三四五六七八九十百千万零两〇\d]+\s*[章节回卷篇集部册]"
        r"(?:\s*第\s*[一二三四五六七八九十百千万零两〇\d]+\s*节)?"
        r"\s*[\]】)）]?(?:\s*[-—:：·.、]\s*|\s+)?[^\n]{0,60}",
        s,
        re.IGNORECASE,
    ):
        return True

    # 单独卷标题
    if re.fullmatch(
        r"[\[【(（]?\s*(?:卷\s*[一二三四五六七八九十百千万零两〇\d]+|"
        r"[一二三四五六七八九十百千万零两〇\d]+\s*卷|"
        r"第\s*[一二三四五六七八九十百千万零两〇\d]+\s*[卷部篇])"
        r"\s*[\]】)）]?(?:\s*[-—:：·.、]\s*|\s+)?[^\n]{0,60}",
        s,
        re.IGNORECASE,
    ):
        return True

    # 特殊章节名
    if re.fullmatch(
        r"[\[【(（]?\s*(?:序章|序言|前言|引言|楔子|正文|尾声|后记|完本感言|"
        r"番外(?:\s*[一二三四五六七八九十百千万零两〇\d]+)?|终章|终卷|大结局|结局)"
        r"\s*[\]】)）]?(?:\s*[-—:：·.、]\s*|\s+)?[^\n]{0,60}",
        s,
        re.IGNORECASE,
    ):
        return True

    # 英文章节
    if re.fullmatch(
        r"(?:Chapter|Part)\s+[A-Za-z0-9IVXLCMivxlcm]+(?:\s*[-—:：.]\s*|\s+)?[^\n]{0,60}",
        s,
        re.IGNORECASE,
    ):
        return True

    # 英文特殊章节
    if re.fullmatch(r"(?:Prologue|Epilogue)", s, re.IGNORECASE):
        return True

    # Markdown 标题
    if re.fullmatch(r"\#{1,3}\s+.+", s):
        return True

    # 数字脏数据标题：1、标题 / 001 标题 / （12）标题
    if re.fullmatch(
        r"[\[【(（]?\s*\d{1,4}\s*[\]】)）]?(?:\s*[-—:：·.、,，]\s*|\s+)[^\n]{1,60}",
        s,
        re.IGNORECASE,
    ):
        return True

    # 纯数字短标题：12 / 001 / 12 终章
    if re.fullmatch(r"\d{1,4}(?:\s+[^\n]{1,20})?", s):
        return len(s) <= 24

    return False


def _merge_consecutive_titles_as_toc(
    chapters: list[tuple[str, str]],
) -> list[tuple[str, str]]:
    """将连续的空内容标题章节合并为"目录"章节，避免标题重复。"""
    if not chapters:
        return chapters

    merged: list[tuple[str, str]] = []
    buffer_titles: list[str] = []

    def flush_buffer():
        nonlocal buffer_titles
        if len(buffer_titles) >= 2:
            merged.append(("目录", "\n".join(buffer_titles)))
        elif len(buffer_titles) == 1:
            merged.append((buffer_titles[0], ""))
        buffer_titles = []

    for title, content in chapters:
        text = content.strip()
        compact = re.sub(r"[\s.\-—_·:：…\d]", "", text)

        is_empty_title_block = (not text) or (len(text) <= 20 and not compact)

        if is_empty_title_block:
            buffer_titles.append(title.strip())
        else:
            flush_buffer()
            merged.append((title, content))

    flush_buffer()
    return merged


def _create_chapter_html(title: str, content: str) -> bytes:
    """创建章节 HTML 内容。"""
    paragraphs = []
    for line in content.split("\n"):
        line = line.strip()
        if line:
            paragraphs.append(f"<p>{html_mod.escape(line)}</p>")

    html_content = "\n".join(paragraphs)

    safe_title = html_mod.escape(title)

    html_doc = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
<head>
    <meta charset="UTF-8"/>
    <title>{safe_title}</title>
    <link rel="stylesheet" type="text/css" href="style/default.css"/>
</head>
<body>
    <h1>{safe_title}</h1>
    {html_content}
</body>
</html>"""

    return html_doc.encode("utf-8")
