"""全文检索 API"""

from litestar import Router, get

from app.services.search import search_documents_service


@get("/")
async def search_documents(
    q: str = "",
    page: int = 1,
    limit: int = 20,
    type: str = "",
    tag: str = "",
) -> dict:
    """FTS5 全文检索

    Args:
        q: 搜索关键词
        page: 页码 (1-based)
        limit: 每页数量
        type: 文件类型过滤（可选，如 document, ebook, text, image, video, audio, archive）
        tag: 标签 UUID 过滤（可选）

    Returns:
        包含搜索结果列表和分页信息的字典
    """
    results, current_page, total_pages, total_count = await search_documents_service(
        q,
        page,
        limit,
        type or None,
        tag or None,
    )
    return {
        "results": results,
        "page": current_page,
        "total_pages": total_pages,
        "total_count": total_count,
    }


search_router = Router(path="/api/search", route_handlers=[search_documents])
