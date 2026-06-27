"""标签管理 API"""
import logging
import uuid as uuid_mod

from litestar import Response, Router, delete, get, patch, post
from litestar.exceptions import HTTPException
from litestar.status_codes import HTTP_400_BAD_REQUEST, HTTP_404_NOT_FOUND, HTTP_409_CONFLICT

from app.database import get_db

logger = logging.getLogger(__name__)


@get("/")
async def list_tags() -> list[dict]:
    """获取所有标签
    
    Returns:
        标签列表，每个标签包含 uuid, name, color
    """
    db = get_db()
    cursor = await db.execute("SELECT uuid, name, color FROM tags ORDER BY name")
    rows = await cursor.fetchall()
    return [{"uuid": r[0], "name": r[1], "color": r[2]} for r in rows]


@post("/")
async def create_tag(data: dict) -> Response:
    """创建标签
    
    Args:
        data: 包含 name (必填) 和 color (可选) 的字典
        
    Returns:
        创建的标签信息，状态码 201
        
    Raises:
        HTTPException: 如果标签名已存在，返回 409
    """
    name = data.get("name", "").strip()
    color = data.get("color", "#409EFF")
    
    if not name:
        raise HTTPException(status_code=400, detail="标签名称不能为空")
    
    db = get_db()
    
    # 检查名称是否已存在
    cursor = await db.execute("SELECT uuid FROM tags WHERE name = ?", (name,))
    existing = await cursor.fetchone()
    
    if existing:
        raise HTTPException(status_code=HTTP_409_CONFLICT, detail="标签名称已存在")
    
    # 生成 uuid 并创建标签
    tag_uuid = str(uuid_mod.uuid4())
    
    await db.execute(
        "INSERT INTO tags (uuid, name, color) VALUES (?, ?, ?)",
        (tag_uuid, name, color)
    )
    await db.commit()
    
    logger.info("标签已创建: %s (%s)", name, tag_uuid)
    
    return Response(
        content={"uuid": tag_uuid, "name": name, "color": color},
        status_code=201,
        media_type="application/json"
    )


@delete("/{uuid:str}", status_code=204)
async def delete_tag(uuid: str) -> None:
    """删除标签
    
    Args:
        uuid: 标签的 UUID
    """
    db = get_db()
    
    await db.execute("DELETE FROM tags WHERE uuid = ?", (uuid,))
    await db.commit()
    
    logger.info("标签已删除: %s", uuid)


@get("/stats")
async def list_tags_with_count() -> list[dict]:
    """获取所有标签及其关联文档数量。"""
    db = get_db()
    cursor = await db.execute(
        """
        SELECT t.uuid, t.name, t.color, COUNT(dt.document_id) as doc_count
        FROM tags t
        LEFT JOIN document_tags dt ON t.id = dt.tag_id
        GROUP BY t.id
        ORDER BY name
        """
    )
    rows = await cursor.fetchall()
    return [{"uuid": r[0], "name": r[1], "color": r[2], "doc_count": r[3]} for r in rows]


@patch("/{uuid:str}")
async def update_tag(uuid: str, data: dict) -> dict:
    """更新标签名称和/或颜色。

    Args:
        uuid: 标签 UUID
        data: 包含 name 和/或 color 的字典
    """
    db = get_db()

    # 检查标签是否存在
    cursor = await db.execute("SELECT id, name, color FROM tags WHERE uuid = ?", (uuid,))
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail="标签不存在")

    tag_id, current_name, current_color = row
    new_name = data.get("name", "").strip() if "name" in data else None
    new_color = data.get("color", "").strip() if "color" in data else None

    if new_name is not None:
        if not new_name:
            raise HTTPException(status_code=HTTP_400_BAD_REQUEST, detail="标签名称不能为空")
        # 检查名称唯一性（排除自身）
        cursor = await db.execute(
            "SELECT uuid FROM tags WHERE name = ? AND uuid != ?", (new_name, uuid)
        )
        if await cursor.fetchone():
            raise HTTPException(status_code=HTTP_409_CONFLICT, detail="标签名称已存在")
        await db.execute("UPDATE tags SET name = ? WHERE id = ?", (new_name, tag_id))

    if new_color is not None:
        await db.execute("UPDATE tags SET color = ? WHERE id = ?", (new_color, tag_id))

    await db.commit()

    # 返回更新后的标签
    cursor = await db.execute("SELECT uuid, name, color FROM tags WHERE id = ?", (tag_id,))
    updated = await cursor.fetchone()
    logger.info("标签已更新: %s (%s)", updated[1], uuid)
    return {"uuid": updated[0], "name": updated[1], "color": updated[2]}


tags_router = Router(path="/api/tags", route_handlers=[list_tags, create_tag, delete_tag, list_tags_with_count, update_tag])
