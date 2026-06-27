"""搜索服务 — 全文检索查询逻辑。"""

import logging
import re
from math import ceil
from pathlib import Path

from app.config import get_settings, get_category_map
from app.database import get_db
from app.services.documents import format_file_size

logger = logging.getLogger(__name__)


def _build_file_type_condition(file_type: str, alias: str = "d") -> tuple[str, list]:
    """根据 file_type 构建 SQL 条件片段和参数列表。"""
    category_map = get_category_map()
    ft_lower = file_type.strip().lower()
    if ft_lower in category_map:
        ext_types = [ext.lstrip(".") for ext in category_map[ft_lower]]
        placeholders = ",".join("?" * len(ext_types))
        return f"{alias}.file_type IN ({placeholders})", ext_types
    else:
        types = [t.strip() for t in file_type.split(",") if t.strip()]
        if len(types) == 1:
            return f"{alias}.file_type = ?", [types[0]]
        elif len(types) > 1:
            placeholders = ",".join("?" * len(types))
            return f"{alias}.file_type IN ({placeholders})", list(types)
    return "", []


async def search_documents_service(
    keyword: str,
    page: int = 1,
    limit: int = 20,
    file_type: str | None = None,
    tag: str | None = None,
) -> tuple[list[dict], int, int, int]:
    """FTS5 全文检索服务函数
    
    Args:
        keyword: 搜索关键词
        page: 页码 (1-based)
        limit: 每页数量
        file_type: 文件类型过滤（可选）
        tag: 标签 UUID 过滤（可选）
        
    Returns:
        (匹配的文档列表, 当前页, 总页数, 总条数)
    """
    if not keyword:
        return [], 1, 1, 0
    
    # 转义 FTS5 特殊字符
    safe_keyword = re.sub(r'[*?"~]', ' ', keyword.strip())
    like_pattern = f"%{safe_keyword}%"
    
    if not safe_keyword:
        return [], 1, 1, 0
    
    # 为 FTS5 准备关键词：每个词用双引号包裹，防止特殊字符导致语法错误
    fts_words = [w for w in safe_keyword.split() if w]
    fts_keyword = ' '.join(f'"{w}"' for w in fts_words) if fts_words else safe_keyword
    
    db = get_db()

    # 构建 file_type 过滤条件
    ft_cond = ""
    ft_params: list = []
    if file_type:
        cond_str, cond_params = _build_file_type_condition(file_type)
        if cond_str:
            ft_cond = f" AND {cond_str}"
            ft_params = cond_params

    # 构建 tag 过滤条件
    tag_cond = ""
    tag_params: list = []
    if tag:
        tag_cond = " AND d.id IN (SELECT dt2.document_id FROM document_tags dt2 JOIN tags t2 ON dt2.tag_id = t2.id WHERE t2.uuid = ?)"
        tag_params = [tag]
    
    try:
        # 先查询总条数（FTS5 + 元数据 + 标签）
        count_sql = f"""
            SELECT COUNT(*) FROM (
                -- FTS5 全文匹配
                SELECT d.id FROM doc_search
                JOIN documents d ON doc_search.rowid = d.id
                WHERE doc_search MATCH ?{ft_cond}{tag_cond}
                
                UNION
                
                -- 元数据 LIKE 匹配
                SELECT d.id FROM documents d
                WHERE (d.title LIKE ?
                   OR d.file_name LIKE ?
                   OR d.summary LIKE ?
                   OR d.authors LIKE ?
                   OR d.meta_data LIKE ?){ft_cond}{tag_cond}
                
                UNION
                
                -- 标签名匹配
                SELECT d.id FROM documents d
                JOIN document_tags dt ON d.id = dt.document_id
                JOIN tags t ON dt.tag_id = t.id
                WHERE t.name LIKE ?{ft_cond}{tag_cond}
            )
        """
        count_params = (
            [fts_keyword] + ft_params + tag_params
            + [like_pattern, like_pattern, like_pattern, like_pattern, like_pattern] + ft_params + tag_params
            + [like_pattern] + ft_params + tag_params
        )
        count_cursor = await db.execute(count_sql, count_params)
        total_count = (await count_cursor.fetchone())[0]
        
        # 计算分页
        total_pages = ceil(total_count / limit) if total_count > 0 else 1
        page = max(1, min(page, total_pages))
        offset = (page - 1) * limit
        
        # 查询当前页数据（FTS5 + 元数据 + 标签，按 sort_group 和 score 排序）
        sql = f"""
            SELECT uuid, title, file_name, file_type, thumbnail_path, snippet,
                   file_size, import_method, imported_time, is_missing, id FROM (
                -- FTS5 全文匹配（sort_group=1，排在元数据之后）
                SELECT d.id, d.uuid, d.title, d.file_name, d.file_type, d.thumbnail_path,
                       snippet(doc_search, 0, '<mark>', '</mark>', '…', 20) AS snippet,
                       d.file_size, d.import_method, d.imported_time, d.is_missing,
                       1 AS sort_group,
                       rank AS score
                FROM doc_search
                JOIN documents d ON doc_search.rowid = d.id
                WHERE doc_search MATCH ?{ft_cond}{tag_cond}

                UNION

                -- 元数据 LIKE 匹配（sort_group=0，排在最前面）
                SELECT d.id, d.uuid, d.title, d.file_name, d.file_type, d.thumbnail_path,
                       NULL AS snippet,
                       d.file_size, d.import_method, d.imported_time, d.is_missing,
                       0 AS sort_group,
                       0 AS score
                FROM documents d
                WHERE (d.title LIKE ?
                   OR d.file_name LIKE ?
                   OR d.summary LIKE ?
                   OR d.authors LIKE ?
                   OR d.meta_data LIKE ?){ft_cond}{tag_cond}
                  AND d.id NOT IN (SELECT rowid FROM doc_search WHERE doc_search MATCH ?)

                UNION

                -- 标签名匹配（sort_group=0，同元数据优先级）
                SELECT d.id, d.uuid, d.title, d.file_name, d.file_type, d.thumbnail_path,
                       NULL AS snippet,
                       d.file_size, d.import_method, d.imported_time, d.is_missing,
                       0 AS sort_group,
                       0 AS score
                FROM documents d
                JOIN document_tags dt ON d.id = dt.document_id
                JOIN tags t ON dt.tag_id = t.id
                WHERE t.name LIKE ?{ft_cond}{tag_cond}
                  AND d.id NOT IN (SELECT rowid FROM doc_search WHERE doc_search MATCH ?)
                  AND d.id NOT IN (
                      SELECT id FROM documents WHERE title LIKE ? OR file_name LIKE ?
                      OR summary LIKE ? OR authors LIKE ? OR meta_data LIKE ?
                  )
            ) sub
            ORDER BY sort_group, score
            LIMIT ? OFFSET ?
        """
        
        query_params = (
            # FTS5 层
            [fts_keyword] + ft_params + tag_params
            # 元数据 LIKE 层
            + [like_pattern, like_pattern, like_pattern, like_pattern, like_pattern] + ft_params + tag_params
            + [fts_keyword]
            # 标签名匹配层
            + [like_pattern] + ft_params + tag_params
            + [fts_keyword]
            + [like_pattern, like_pattern, like_pattern, like_pattern, like_pattern]
            # 分页
            + [limit, offset]
        )
        
        cursor = await db.execute(sql, query_params)
        rows = await cursor.fetchall()
        
        settings = get_settings()
        results = []
        doc_ids: list[int] = []
        for row in rows:
            doc_id = row[10]
            import_method = row[7]
            doc = {
                "uuid": row[0],
                "title": row[1],
                "file_name": row[2],
                "file_type": row[3],
                "thumbnail_path": row[4],
                "snippet": row[5],
                "file_size": row[6],
                "file_size_display": format_file_size(row[6]),
                "import_method": import_method,
                "imported_time": row[8],
                "is_missing": bool(row[9]),
                "tags": [],
            }

            # 上传文件路径补全
            if import_method == "upload":
                doc["file_path"] = str(settings.LIBRARY_ROOT.resolve() / (row[2] or ""))

            doc_ids.append(doc_id)
            results.append(doc)

        # 批量查询标签，避免 N+1 问题
        if doc_ids:
            placeholders = ",".join("?" * len(doc_ids))
            tag_sql = f"""
                SELECT dt.document_id, t.uuid, t.name, t.color
                FROM tags t
                JOIN document_tags dt ON t.id = dt.tag_id
                WHERE dt.document_id IN ({placeholders})
            """
            tag_cursor = await db.execute(tag_sql, doc_ids)
            tag_rows = await tag_cursor.fetchall()
            # 构建 document_id -> tags 映射
            tags_map: dict[int, list[dict]] = {}
            for did, tag_uuid, tag_name, tag_color in tag_rows:
                tags_map.setdefault(did, []).append(
                    {"uuid": tag_uuid, "name": tag_name, "color": tag_color}
                )
            # 将标签分配到对应文档
            for idx, doc in enumerate(results):
                doc["tags"] = tags_map.get(doc_ids[idx], [])
        
        return results, page, total_pages, total_count
    
    except Exception as e:
        logger.error("搜索失败: %s", e, exc_info=True)
        return [], 1, 1, 0
