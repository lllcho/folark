"""插件执行与管理 API。"""

import json
import logging

from litestar import Router, get, patch, post
from litestar.exceptions import HTTPException
from litestar.status_codes import HTTP_400_BAD_REQUEST, HTTP_404_NOT_FOUND

from app.config import get_settings, resolve_file_path
from app.database import get_db
from app.plugins.core import (
    PIPELINE_HANDLER_TYPES,
    PluginContext,
    persist_task_result,
)
from app.plugins.manager import get_plugin_manager

logger = logging.getLogger(__name__)


@post("/plugins/{plugin_name:str}/handlers/{handler_name:str}/execute")
async def execute_plugin(
    plugin_name: str,
    handler_name: str,
    document_id: int,
) -> dict:
    """
    执行指定插件的某个处理器。

    通过 plugin_name + handler_name 定位处理器。
    """
    manager = get_plugin_manager()
    settings = get_settings()
    db = get_db()

    # 1. 查找任务处理器
    handler_info = manager.get_handler_info(plugin_name, handler_name)
    if handler_info is None:
        raise HTTPException(
            status_code=HTTP_404_NOT_FOUND,
            detail=f"处理器不存在: {plugin_name}/{handler_name}",
        )

    # 1.5 检查启用状态
    plugin_instance = manager.get_plugin(plugin_name)
    if not plugin_instance or not plugin_instance.enabled:
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail=f"插件已禁用: {plugin_name}",
        )
    task_handler = manager.handler_registry.get((plugin_name, handler_name))
    if task_handler and not task_handler.enabled:
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail=f"处理器已禁用: {plugin_name}/{handler_name}",
        )

    handler_type = handler_info.handler_type

    # 2. 仅允许 PIPELINE_HANDLER_TYPES (extract/thumbnail/summarize)
    if handler_type not in PIPELINE_HANDLER_TYPES:
        valid_values = [t.value for t in PIPELINE_HANDLER_TYPES]
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail=f"仅允许执行 pipeline 处理器: {valid_values}",
        )

    async with db.execute(
        """SELECT d.id, d.uuid, d.file_name, d.file_path, d.file_type,
                  d.file_size, d.title, d.authors, d.summary, d.meta_data,
                  d.thumbnail_path, d.import_method,
                  dt.plain_text
           FROM documents d
           LEFT JOIN document_texts dt ON d.id = dt.document_id
           WHERE d.id = ?""",
        (document_id,),
    ) as cursor:
        row = await cursor.fetchone()

    if not row:
        raise HTTPException(
            status_code=HTTP_404_NOT_FOUND,
            detail=f"文档不存在: document_id={document_id}",
        )

    # 4. 构建 PluginContext
    (
        doc_id,
        uuid,
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
        plain_text,
    ) = row

    file_path = resolve_file_path(file_path_str, import_method)

    ctx = PluginContext(
        id=doc_id,
        uuid=uuid,
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

    # 5. 执行插件
    import asyncio

    result = await asyncio.to_thread(manager.execute, plugin_name, handler_name, ctx)

    # 6. 处理结果并持久化
    result_summary = await persist_task_result(
        handler_type,
        result,
        db,
        document_id,
        uuid=uuid,
        settings=settings,
    )
    result_summary.update({"plugin": plugin_name, "handler_name": handler_name, "document_id": document_id})

    return result_summary


# ── 插件管理 API ───────────────────────────────────────────────


@get("/plugins/handlers")
async def list_pipeline_handlers() -> list[dict]:
    """获取可用于批量执行的 handler 列表。

    返回 PIPELINE_HANDLER_TYPES 中所有已启用的 handler 扁平列表。
    """
    manager = get_plugin_manager()
    handlers = []
    for (plugin_name, handler_name), handler in manager.handler_registry.items():
        if handler.info.handler_type in PIPELINE_HANDLER_TYPES and handler.enabled:
            handlers.append(
                {
                    "plugin_name": plugin_name,
                    "handler_name": handler_name,
                    "handler_type": handler.info.handler_type.value,
                    "handler_mode": handler.info.handler_mode.value,
                    "source_types": handler.info.source_types,
                    "description": handler.info.description,
                    "enabled": handler.enabled,
                }
            )
    return handlers


@get("/plugins")
async def list_plugins() -> list[dict]:
    """列出所有插件及其任务。"""
    db = get_db()

    async with db.execute(
        "SELECT name, version, plugin_type, enabled, config, task_handlers, installed_at, updated_at FROM plugins ORDER BY id"
    ) as cursor:
        rows = await cursor.fetchall()

    manager = get_plugin_manager()
    result = []
    for row in rows:
        name, version, plugin_type, enabled, config, task_handlers, installed_at, updated_at = row
        tasks = []
        if task_handlers:
            try:
                tasks = json.loads(task_handlers)
            except (json.JSONDecodeError, TypeError):
                pass

        # 从内存插件实例获取 default_config 和当前 config
        plugin_instance = manager.get_plugin(name)
        default_config = plugin_instance.default_config if plugin_instance else {}
        current_config = plugin_instance.config if plugin_instance else (json.loads(config) if config else {})

        result.append(
            {
                "name": name,
                "version": version,
                "plugin_type": plugin_type,
                "enabled": bool(enabled),
                "default_config": default_config,
                "config": current_config,
                "tasks": tasks,
                "installed_at": installed_at,
                "updated_at": updated_at,
            }
        )

    return result


@patch("/plugins/{plugin_name:str}")
async def update_plugin(plugin_name: str, data: dict) -> dict:
    """更新插件配置（启用/禁用插件）。"""
    db = get_db()

    # 检查插件是否存在
    async with db.execute("SELECT id FROM plugins WHERE name = ?", (plugin_name,)) as cursor:
        row = await cursor.fetchone()
    if not row:
        raise HTTPException(
            status_code=HTTP_404_NOT_FOUND,
            detail=f"插件不存在: {plugin_name}",
        )

    # 支持的字段
    if "enabled" in data:
        enabled = 1 if data["enabled"] else 0
        await db.execute(
            "UPDATE plugins SET enabled = ?, updated_at = CURRENT_TIMESTAMP WHERE name = ?",
            (enabled, plugin_name),
        )

    if "config" in data:
        config_value = data["config"]
        if not isinstance(config_value, dict):
            raise HTTPException(
                status_code=HTTP_400_BAD_REQUEST,
                detail="config 必须是字典类型",
            )
        await db.execute(
            "UPDATE plugins SET config = ?, updated_at = CURRENT_TIMESTAMP WHERE name = ?",
            (json.dumps(config_value, ensure_ascii=False), plugin_name),
        )

    await db.commit()

    # 同步内存状态
    manager = get_plugin_manager()
    plugin_instance = manager.get_plugin(plugin_name)
    if plugin_instance is not None:
        if "enabled" in data:
            plugin_instance.enabled = bool(data["enabled"])
        if "config" in data:
            plugin_instance.update_config(data["config"])

    return {"name": plugin_name, "status": "updated"}


@patch("/plugins/{plugin_name:str}/handlers/{handler_name:str}")
async def update_plugin_handler(
    plugin_name: str,
    handler_name: str,
    data: dict,
) -> dict:
    """更新单个处理器配置（启用/禁用），通过 handler_name 定位。"""
    db = get_db()

    # 读取插件记录
    async with db.execute("SELECT task_handlers FROM plugins WHERE name = ?", (plugin_name,)) as cursor:
        row = await cursor.fetchone()
    if not row:
        raise HTTPException(
            status_code=HTTP_404_NOT_FOUND,
            detail=f"插件不存在: {plugin_name}",
        )

    task_handlers = row[0]
    if not task_handlers:
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail="插件没有处理器",
        )

    try:
        handlers = json.loads(task_handlers)
    except (json.JSONDecodeError, TypeError):
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail="插件处理器数据损坏",
        )

    # 通过 handler_name 查找处理器
    target_handler = None
    for t in handlers:
        if t.get("handler_name") == handler_name:
            target_handler = t
            break

    if target_handler is None:
        raise HTTPException(
            status_code=HTTP_404_NOT_FOUND,
            detail=f"处理器不存在: {handler_name}",
        )

    # 支持的字段
    if "enabled" in data:
        target_handler["enabled"] = 1 if data["enabled"] else 0

    await db.execute(
        "UPDATE plugins SET task_handlers = ?, updated_at = CURRENT_TIMESTAMP WHERE name = ?",
        (json.dumps(handlers, ensure_ascii=False), plugin_name),
    )
    await db.commit()

    # 同步内存状态
    manager = get_plugin_manager()
    handler_key = (plugin_name, handler_name)
    task_handler = manager.handler_registry.get(handler_key)
    if task_handler is not None:
        task_handler.enabled = bool(target_handler.get("enabled", 1))

    return {
        "name": plugin_name,
        "handler_name": handler_name,
        "handler": target_handler,
        "status": "updated",
    }


plugins_router = Router(
    path="/api",
    route_handlers=[execute_plugin, list_pipeline_handlers, list_plugins, update_plugin, update_plugin_handler],
)
