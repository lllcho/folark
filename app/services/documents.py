"""文档服务 — 文档 CRUD、标签管理与 PluginContext 构建。"""

import logging
import uuid as uuid_mod
from math import ceil

from app.config import get_category_map, get_settings, resolve_file_path
from app.database import get_db
from app.plugins.core import PluginContext

logger = logging.getLogger(__name__)


def format_file_size(size: int | None) -> str:
    """将文件大小格式化为人类可读的字符串。"""
    if size is None:
        return "未知"
    for unit in ["B", "KB", "MB", "GB"]:
        if size < 1024:
            return f"{size:.1f} {unit}" if unit != "B" else f"{size} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


# 排序字段映射：前端参数 -> (SQL ORDER BY 表达式)
_SORT_OPTIONS: dict[str, str] = {
    "default": "imported_time DESC, documents.id DESC",
    "name_asc": "file_name COLLATE NOCASE ASC, documents.id ASC",
    "name_desc": "file_name COLLATE NOCASE DESC, documents.id DESC",
    "size_asc": "file_size ASC, documents.id ASC",
    "size_desc": "file_size DESC, documents.id DESC",
    "date_asc": "file_modified_time ASC, documents.id ASC",
    "date_desc": "file_modified_time DESC, documents.id DESC",
}


async def list_documents_service(
    page: int = 1,
    limit: int = 20,
    file_type: str | None = None,
    tag: str | None = None,
    sort: str | None = None,
) -> tuple[list[dict], int, int, int]:
    """文档列表查询服务。

    支持逗号分隔的多类型筛选，如 ``"txt,md"``。
    支持按标签 UUID 筛选。
    支持排序：default / name_asc / name_desc / size_asc / size_desc / date_asc / date_desc。

    Returns:
        (documents, current_page, total_pages, total_count)
    """
    db = get_db()

    # 构建查询条件
    conditions: list[str] = []
    params: list = []
    join_clause = ""

    # 标签筛选
    if tag:
        join_clause = "JOIN document_tags dt ON documents.id = dt.document_id JOIN tags t ON dt.tag_id = t.id"
        conditions.append("t.uuid = ?")
        params.append(tag)

    if file_type:
        category_map = get_category_map()
        ft_lower = file_type.strip().lower()
        if ft_lower in category_map:
            # 去掉前导点，转为不带点的扩展名列表
            ext_types = [ext.lstrip(".") for ext in category_map[ft_lower]]
            placeholders = ",".join("?" * len(ext_types))
            conditions.append(f"file_type IN ({placeholders})")
            params.extend(ext_types)
        else:
            types = [t.strip() for t in file_type.split(",") if t.strip()]
            if len(types) == 1:
                conditions.append("file_type = ?")
                params.append(types[0])
            elif len(types) > 1:
                placeholders = ",".join("?" * len(types))
                conditions.append(f"file_type IN ({placeholders})")
                params.extend(types)

    where_clause = ""
    if conditions:
        where_clause = "WHERE " + " AND ".join(conditions)

    # 查询总条数
    count_sql = f"SELECT COUNT(*) FROM documents {join_clause} {where_clause}"
    async with db.execute(count_sql, params) as cursor:
        total_count = (await cursor.fetchone())[0]

    # 计算分页
    total_pages = ceil(total_count / limit) if total_count > 0 else 1
    page = max(1, min(page, total_pages))
    offset = (page - 1) * limit

    # 查询当前页数据（取 API 和 Fragment 的字段并集）
    sql = f"""
        SELECT documents.id, documents.uuid, file_name, file_path, source_dir, import_method,
               file_type, file_size, file_hash, file_modified_time,
               title, thumbnail_path, is_missing, imported_time
        FROM documents
        {join_clause}
        {where_clause}
        ORDER BY {_SORT_OPTIONS.get(sort or "default", _SORT_OPTIONS["default"])}
        LIMIT ? OFFSET ?
    """
    query_params = params + [limit, offset]

    documents: list[dict] = []
    doc_ids: list[int] = []
    async with db.execute(sql, query_params) as cursor:
        rows = await cursor.fetchall()
        for row in rows:
            doc_id = row[0]
            file_path = row[3]
            import_method = row[5]
            file_path = str(resolve_file_path(file_path, import_method)) if file_path else file_path
            doc = {
                "id": doc_id,
                "uuid": row[1],
                "file_name": row[2],
                "file_path": file_path,
                "source_dir": row[4],
                "import_method": import_method,
                "file_type": row[6],
                "file_size": row[7],
                "file_size_display": format_file_size(row[7]),
                "file_hash": row[8],
                "file_modified_time": row[9],
                "title": row[10],
                "thumbnail_path": row[11],
                "is_missing": bool(row[12]),
                "imported_time": row[13],
                "tags": [],
            }
            doc_ids.append(doc_id)
            documents.append(doc)

    # 批量查询标签，避免 N+1 问题
    if doc_ids:
        placeholders = ",".join("?" * len(doc_ids))
        tag_sql = f"""
            SELECT dt.document_id, t.uuid, t.name, t.color
            FROM tags t
            JOIN document_tags dt ON t.id = dt.tag_id
            WHERE dt.document_id IN ({placeholders})
        """
        async with db.execute(tag_sql, doc_ids) as tag_cursor:
            tag_rows = await tag_cursor.fetchall()
        # 构建 document_id -> tags 映射
        tags_map: dict[int, list[dict]] = {}
        for doc_id, tag_uuid, tag_name, tag_color in tag_rows:
            tags_map.setdefault(doc_id, []).append({"uuid": tag_uuid, "name": tag_name, "color": tag_color})
        # 将标签分配到对应文档
        for doc in documents:
            doc["tags"] = tags_map.get(doc["id"], [])

    return documents, page, total_pages, total_count


async def get_document_service(uuid: str) -> dict | None:
    """文档详情查询服务，返回文档详情字典，不存在则返回 None。"""
    db = get_db()

    # 查询文档（JOIN document_texts 一次获取文本信息）
    async with db.execute(
        """
        SELECT d.id, d.uuid, d.file_name, d.file_path, d.source_dir, d.import_method,
               d.file_type, d.file_size, d.file_hash, d.file_modified_time,
               d.title, d.authors, d.thumbnail_path, d.meta_data, d.summary,
               d.is_missing, d.imported_time,
               dt.plain_text, dt.word_count
        FROM documents d
        LEFT JOIN document_texts dt ON d.id = dt.document_id
        WHERE d.uuid = ?
        """,
        (uuid,),
    ) as cursor:
        row = await cursor.fetchone()

    if not row:
        return None

    doc_id = row[0]
    file_path = row[3]
    import_method = row[5]
    file_path = str(resolve_file_path(file_path, import_method)) if file_path else file_path

    doc = {
        "id": doc_id,
        "uuid": row[1],
        "file_name": row[2],
        "file_path": file_path,
        "source_dir": row[4],
        "import_method": import_method,
        "file_type": row[6],
        "file_size": row[7],
        "file_size_display": format_file_size(row[7]),
        "file_hash": row[8],
        "file_modified_time": row[9],
        "title": row[10],
        "authors": row[11],
        "thumbnail_path": row[12],
        "meta_data": row[13],
        "summary": row[14],
        "is_missing": bool(row[15]),
        "imported_time": row[16],
        # 兼容 Fragment 层的顶层字段
        "plain_text": row[17],
        "word_count": row[18] or 0,
        # 兼容 API 层的嵌套字段
        "text": {"plain_text": row[17], "word_count": row[18]} if row[17] is not None else None,
        "tags": [],
    }

    # 查询标签
    async with db.execute(
        """
        SELECT t.uuid, t.name, t.color
        FROM tags t
        JOIN document_tags dt ON t.id = dt.tag_id
        WHERE dt.document_id = ?
        """,
        (doc_id,),
    ) as tag_cursor:
        tags = await tag_cursor.fetchall()
        doc["tags"] = [{"uuid": t[0], "name": t[1], "color": t[2]} for t in tags]

    return doc


# ---------------------------------------------------------------------------
# 文档更新服务
# ---------------------------------------------------------------------------


async def _get_doc_id_by_uuid(uuid: str) -> int:
    """根据 UUID 查询文档 ID，不存在则抛出 ValueError。"""
    db = get_db()
    async with db.execute("SELECT id FROM documents WHERE uuid = ?", (uuid,)) as cursor:
        row = await cursor.fetchone()
    if not row:
        raise ValueError("文档不存在")
    return row[0]


# 允许通过 PATCH 更新的字段白名单
_EDITABLE_FIELDS = {"title", "authors", "summary", "meta_data"}


async def update_document_fields(uuid: str, fields: dict) -> None:
    """更新文档的可编辑字段（title, authors, summary, meta_data）。

    对 authors 和 meta_data 做 JSON 序列化；其他字段直接存储字符串。
    """
    import json

    db = get_db()
    doc_id = await _get_doc_id_by_uuid(uuid)

    updates: list[tuple[str, object]] = []
    for key, value in fields.items():
        if key not in _EDITABLE_FIELDS:
            continue
        if key in ("authors", "meta_data"):
            # 确保以 JSON 字符串形式存入数据库
            if isinstance(value, (list, dict)):
                value = json.dumps(value, ensure_ascii=False)
        updates.append((key, value))

    if not updates:
        return

    set_clause = ", ".join(f"{col} = ?" for col, _ in updates)
    params = [val for _, val in updates] + [doc_id]
    await db.execute(f"UPDATE documents SET {set_clause} WHERE id = ?", params)
    await db.commit()
    logger.info("文档字段已更新: uuid=%s, fields=%s", uuid, [c for c, _ in updates])


async def replace_document_tags(uuid: str, tag_uuids: list[str]) -> None:
    """替换文档的全部标签关联（先删后插）。"""
    db = get_db()
    doc_id = await _get_doc_id_by_uuid(uuid)

    # 删除旧关联
    await db.execute("DELETE FROM document_tags WHERE document_id = ?", (doc_id,))

    # 批量查询所有 tag_id
    if tag_uuids:
        placeholders = ",".join("?" * len(tag_uuids))
        async with db.execute(f"SELECT id FROM tags WHERE uuid IN ({placeholders})", tag_uuids) as tag_cursor:
            tag_rows = await tag_cursor.fetchall()
        tag_ids = [row[0] for row in tag_rows]

        # 批量插入新关联
        if tag_ids:
            await db.executemany(
                "INSERT INTO document_tags (document_id, tag_id) VALUES (?, ?)",
                [(doc_id, tid) for tid in tag_ids],
            )

    await db.commit()


async def _get_or_create_tag_id(db, tag_name: str) -> int | None:
    """按名称查找标签，不存在则自动创建，返回 tag id。空名称返回 None。"""
    tag_name = tag_name.strip()
    if not tag_name:
        return None

    async with db.execute("SELECT id FROM tags WHERE name = ?", (tag_name,)) as cur:
        tag_row = await cur.fetchone()

    if tag_row:
        return tag_row[0]

    tag_uuid = str(uuid_mod.uuid4())
    await db.execute(
        "INSERT INTO tags (uuid, name, color) VALUES (?, ?, ?)",
        (tag_uuid, tag_name, "#409EFF"),
    )
    async with db.execute("SELECT id FROM tags WHERE uuid = ?", (tag_uuid,)) as cur:
        return (await cur.fetchone())[0]


async def add_document_tags(uuid: str, tag_names: list[str]) -> None:
    """按名称增量添加标签，自动创建不存在的标签。"""
    db = get_db()
    doc_id = await _get_doc_id_by_uuid(uuid)

    # 预处理标签：查找或创建
    tag_ids: list[int] = []
    for tag_name in tag_names:
        tag_id = await _get_or_create_tag_id(db, tag_name)
        if tag_id is not None:
            tag_ids.append(tag_id)

    # 批量插入关联
    if tag_ids:
        await db.executemany(
            "INSERT OR IGNORE INTO document_tags (document_id, tag_id) VALUES (?, ?)",
            [(doc_id, tid) for tid in tag_ids],
        )

    await db.commit()


async def remove_document_tag_service(doc_uuid: str, tag_uuid: str) -> None:
    """从文档中移除指定标签。文档或标签不存在时抛出 ValueError。"""
    db = get_db()
    doc_id = await _get_doc_id_by_uuid(doc_uuid)

    async with db.execute("SELECT id FROM tags WHERE uuid = ?", (tag_uuid,)) as cursor:
        tag_row = await cursor.fetchone()

    if not tag_row:
        raise ValueError("标签不存在")

    tag_id = tag_row[0]

    await db.execute(
        "DELETE FROM document_tags WHERE document_id = ? AND tag_id = ?",
        (doc_id, tag_id),
    )
    await db.commit()
    logger.info("标签已从文档移除: doc_uuid=%s, tag_uuid=%s", doc_uuid, tag_uuid)


async def batch_delete_documents_service(uuids: list[str]) -> int:
    """批量删除文档记录，返回实际删除的数量。未找到任何匹配时抛出 ValueError。"""
    db = get_db()

    placeholders = ",".join("?" * len(uuids))
    async with db.execute(f"SELECT uuid FROM documents WHERE uuid IN ({placeholders})", uuids) as cursor:
        found_rows = await cursor.fetchall()
    found_uuids = [row[0] for row in found_rows]

    if not found_uuids:
        raise ValueError("未找到任何匹配的文档")

    placeholders = ",".join("?" * len(found_uuids))
    await db.execute(
        f"DELETE FROM documents WHERE uuid IN ({placeholders})",
        found_uuids,
    )
    await db.commit()

    deleted_count = len(found_uuids)
    logger.info("批量删除文档: 共 %d 条", deleted_count)
    return deleted_count


async def update_document_thumbnail(uuid: str, image_bytes: bytes) -> str:
    """更新文档自定义缩略图。

    将上传的图片处理为标准缩略图并保存，更新数据库中的 thumbnail_path。
    返回缩略图的相对路径。
    """
    from io import BytesIO

    from PIL import Image

    db = get_db()
    settings = get_settings()
    doc_id = await _get_doc_id_by_uuid(uuid)

    # 用 PIL 打开图片
    try:
        img = Image.open(BytesIO(image_bytes))
    except Exception as e:
        raise ValueError(f"无法识别图片文件: {e}")

    # 标准化缩略图：缩放到 300x400，RGBA/P 转 RGB
    img.thumbnail((300, 400))
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")

    # 保存到 .thumbnails/{uuid}.jpg
    thumbnails_dir = settings.LIBRARY_ROOT / ".thumbnails"
    thumbnails_dir.mkdir(parents=True, exist_ok=True)
    output_path = thumbnails_dir / f"{uuid}.jpg"
    img.save(output_path, "JPEG", quality=85)

    rel_path = f".thumbnails/{uuid}.jpg"
    await db.execute(
        "UPDATE documents SET thumbnail_path = ? WHERE id = ?",
        (rel_path, doc_id),
    )
    await db.commit()
    logger.info("文档缩略图已更新: uuid=%s, path=%s", uuid, rel_path)
    return rel_path


async def batch_add_tags_service(uuids: list[str], tag_names: list[str]) -> int:
    """批量为多个文档添加标签，返回实际处理的文档数量。

    自动创建不存在的标签。
    """
    db = get_db()

    # 查找所有匹配的文档 id
    placeholders = ",".join("?" * len(uuids))
    async with db.execute(f"SELECT id, uuid FROM documents WHERE uuid IN ({placeholders})", uuids) as cursor:
        found_rows = await cursor.fetchall()

    if not found_rows:
        raise ValueError("未找到任何匹配的文档")

    # 预处理标签：查找或创建
    tag_ids: list[int] = []
    for tag_name in tag_names:
        tag_id = await _get_or_create_tag_id(db, tag_name)
        if tag_id is not None:
            tag_ids.append(tag_id)

    # 批量为所有文档关联所有标签
    pairs = [(doc_id, tag_id) for doc_id, _ in found_rows for tag_id in tag_ids]
    if pairs:
        await db.executemany(
            "INSERT OR IGNORE INTO document_tags (document_id, tag_id) VALUES (?, ?)",
            pairs,
        )

    await db.commit()
    processed = len(found_rows)
    logger.info("批量添加标签: %d 个文档, %d 个标签", processed, len(tag_ids))
    return processed


# ---------------------------------------------------------------------------
# PluginContext 构建服务
# ---------------------------------------------------------------------------


async def build_plugin_context(uuid: str) -> PluginContext:
    """查询文档完整信息并构建 PluginContext。

    文档不存在或文件丢失时抛出 ValueError / FileNotFoundError。
    """
    db = get_db()
    settings = get_settings()

    async with db.execute(
        """SELECT d.id, d.uuid, d.file_name, d.file_path, d.file_type,
                  d.file_size, d.title, d.authors, d.summary, d.meta_data,
                  d.thumbnail_path, d.import_method, d.is_missing,
                  dt.plain_text
           FROM documents d
           LEFT JOIN document_texts dt ON d.id = dt.document_id
           WHERE d.uuid = ?""",
        (uuid,),
    ) as cursor:
        row = await cursor.fetchone()

    if not row:
        raise ValueError("文档不存在")

    (
        doc_id,
        doc_uuid,
        file_name,
        file_path_str,
        file_type,
        file_size,
        title,
        authors,
        summary,
        meta_data,
        thumbnail_path,
        import_method,
        is_missing,
        plain_text,
    ) = row

    if is_missing:
        raise FileNotFoundError("文件已丢失")

    # 解析文件路径
    file_path = resolve_file_path(file_path_str, import_method)

    if not file_path.exists():
        raise FileNotFoundError("文件不存在于磁盘上")

    return PluginContext(
        id=doc_id,
        uuid=doc_uuid,
        file_name=file_name,
        file_path=file_path,
        file_type=file_type,
        file_size=file_size,
        title=title,
        authors=authors,
        summary=summary,
        meta_data=meta_data,
        thumbnail_path=thumbnail_path,
        plain_text=plain_text,
        settings=settings,
    )
