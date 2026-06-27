"""批量任务执行服务 — 创建、执行、控制和查询批量任务。"""

import asyncio
import json
import logging
import uuid as uuid_lib

from app.config import get_settings, resolve_file_path
from app.database import get_db
from app.plugins.core import (
    PIPELINE_HANDLER_TYPES,
    PluginContext,
    TaskHandlerMode,
    expand_source_types,
    persist_task_result,
)
from app.plugins.manager import get_plugin_manager

logger = logging.getLogger(__name__)

# 内存中跟踪运行中的 asyncio.Task
_running_tasks: dict[str, asyncio.Task] = {}


async def create_batch_job(document_uuids: list[str], handlers: list[dict]) -> dict:
    """
    创建批量任务。

    1. 查询 document_uuids 对应的 document_id 和 file_type
    2. 对每个 (document, handler) 预检查 source_type 匹配
    3. 只插入匹配的 items
    4. 计算 skipped_count
    5. 启动异步执行
    """
    db = get_db()
    manager = get_plugin_manager()

    # 查询文档信息
    placeholders = ",".join("?" * len(document_uuids))
    async with db.execute(
        f"SELECT id, uuid, file_type FROM documents WHERE uuid IN ({placeholders})",
        document_uuids,
    ) as cursor:
        doc_rows = await cursor.fetchall()

    # doc_id -> (uuid, file_type)
    doc_map: dict[int, tuple[str, str]] = {}
    for row in doc_rows:
        doc_map[row[0]] = (row[1], row[2])

    document_count = len(doc_map)
    job_uuid = str(uuid_lib.uuid4())

    # 预检查 source_type 匹配，构建待插入 items
    items_to_insert: list[tuple[int, str, str]] = []  # (document_id, plugin_name, handler_name)

    for handler_spec in handlers:
        plugin_name = handler_spec["plugin_name"]
        handler_name = handler_spec["handler_name"]

        # 从 handler_registry 获取 handler 信息
        task_handler = manager.handler_registry.get((plugin_name, handler_name))
        if task_handler is None:
            continue

        # 展开 source_types
        expanded = expand_source_types(task_handler.info.source_types)

        for doc_id, (doc_uuid, file_type) in doc_map.items():
            if file_type in expanded:
                items_to_insert.append((doc_id, plugin_name, handler_name))

    total_items = len(items_to_insert)
    skipped_count = document_count * len(handlers) - total_items

    # 插入 batch_jobs 记录
    handlers_json = json.dumps(handlers, ensure_ascii=False)
    await db.execute(
        """INSERT INTO batch_jobs (uuid, status, document_count, handlers, total_items, skipped_count)
           VALUES (?, 'running', ?, ?, ?, ?)""",
        (job_uuid, document_count, handlers_json, total_items, skipped_count),
    )

    # 获取 job_id
    async with db.execute("SELECT id FROM batch_jobs WHERE uuid = ?", (job_uuid,)) as cursor:
        job_row = await cursor.fetchone()
    job_id = job_row[0]

    # 批量插入 items
    if items_to_insert:
        await db.executemany(
            "INSERT INTO batch_job_items (job_id, document_id, plugin_name, handler_name) VALUES (?, ?, ?, ?)",
            [(job_id, doc_id, pn, hn) for doc_id, pn, hn in items_to_insert],
        )

    # 更新 started_at
    await db.execute(
        "UPDATE batch_jobs SET started_at = datetime('now','localtime') WHERE id = ?",
        (job_id,),
    )
    await db.commit()

    # 启动异步执行
    task = asyncio.create_task(run_batch_job(job_uuid))
    _running_tasks[job_uuid] = task

    logger.info("批量任务已创建: uuid=%s, total_items=%d, skipped=%d", job_uuid, total_items, skipped_count)

    return {
        "uuid": job_uuid,
        "status": "running",
        "total_items": total_items,
        "skipped_count": skipped_count,
        "document_count": document_count,
    }


async def create_pipeline_batch_job(document_uuids: list[str]) -> dict:
    """
    为已导入的文档自动创建即时流水线批量任务。

    遍历 handler_registry，筛选出 PIPELINE_HANDLER_TYPES 中
    模式为 INSTANT、插件类型为 builtin、且已启用的 handler，
    复用 create_batch_job 完成任务的创建与启动。
    """
    manager = get_plugin_manager()

    handlers: list[dict] = []
    for handler in manager.handler_registry.values():
        if handler.info.handler_type not in PIPELINE_HANDLER_TYPES:
            continue
        if handler.info.handler_mode != TaskHandlerMode.INSTANT:
            continue
        if handler.plugin.plugin_type != "builtin":
            continue
        if not handler.enabled:
            continue
        handlers.append(
            {
                "plugin_name": handler.plugin.name,
                "handler_name": handler.info.handler_name,
            }
        )

    return await create_batch_job(document_uuids, handlers)


async def run_batch_job(job_uuid: str) -> None:
    """
    异步执行主循环。

    逐条执行 pending items，每步检查 job status，
    成功时 persist_task_result，失败时记录 error_message。
    """
    db = get_db()
    manager = get_plugin_manager()
    settings = get_settings()

    try:
        # 查询 job_id
        async with db.execute("SELECT id FROM batch_jobs WHERE uuid = ?", (job_uuid,)) as cursor:
            job_row = await cursor.fetchone()
        if not job_row:
            logger.error("批量任务不存在: %s", job_uuid)
            return
        job_id = job_row[0]

        # 查询所有 pending items
        async with db.execute(
            """SELECT bi.id, bi.document_id, bi.plugin_name, bi.handler_name
               FROM batch_job_items bi
               WHERE bi.job_id = ? AND bi.status = 'pending'
               ORDER BY bi.document_id, bi.plugin_name, bi.handler_name""",
            (job_id,),
        ) as cursor:
            pending_items = await cursor.fetchall()

        for item_row in pending_items:
            item_id, document_id, plugin_name, handler_name = item_row

            # 检查 job 状态（paused/cancelled 则停止）
            async with db.execute("SELECT status FROM batch_jobs WHERE id = ?", (job_id,)) as cursor:
                status_row = await cursor.fetchone()
            if status_row and status_row[0] in ("paused", "cancelled"):
                logger.info("批量任务 %s 状态为 %s，停止执行", job_uuid, status_row[0])
                break

            # 标记 item 为 running
            await db.execute(
                "UPDATE batch_job_items SET status = 'running', started_at = datetime('now','localtime') WHERE id = ?",
                (item_id,),
            )
            await db.commit()

            try:
                # 查询文档信息构建 PluginContext
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
                    doc_row = await cursor.fetchone()

                if not doc_row:
                    raise ValueError(f"文档不存在: document_id={document_id}")

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
                    plain_text,
                ) = doc_row

                file_path = resolve_file_path(file_path_str, import_method)

                ctx = PluginContext(
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

                # 执行 handler
                result = await asyncio.to_thread(manager.execute, plugin_name, handler_name, ctx)

                # 持久化结果
                handler_info = manager.get_handler_info(plugin_name, handler_name)
                if handler_info:
                    await persist_task_result(
                        handler_info.handler_type,
                        result,
                        db,
                        document_id,
                        uuid=doc_uuid,
                        settings=settings,
                    )

                # 标记 item 成功
                await db.execute(
                    "UPDATE batch_job_items SET status = 'success', completed_at = datetime('now','localtime') WHERE id = ?",
                    (item_id,),
                )
                await db.execute(
                    "UPDATE batch_jobs SET success_count = success_count + 1 WHERE id = ?",
                    (job_id,),
                )
                await db.commit()

            except Exception as e:
                logger.warning(
                    "批量任务 item 执行失败: job=%s, item=%d, error=%s",
                    job_uuid,
                    item_id,
                    str(e),
                    exc_info=True,
                )
                error_msg = str(e)[:500]
                await db.execute(
                    "UPDATE batch_job_items SET status = 'failed', error_message = ?, completed_at = datetime('now','localtime') WHERE id = ?",
                    (error_msg, item_id),
                )
                await db.execute(
                    "UPDATE batch_jobs SET failed_count = failed_count + 1 WHERE id = ?",
                    (job_id,),
                )
                await db.commit()

        # 检查最终状态：如果不是 paused/cancelled，标记为 completed
        async with db.execute("SELECT status FROM batch_jobs WHERE id = ?", (job_id,)) as cursor:
            final_status = await cursor.fetchone()
        if final_status and final_status[0] == "running":
            await db.execute(
                "UPDATE batch_jobs SET status = 'completed', completed_at = datetime('now','localtime') WHERE id = ?",
                (job_id,),
            )
            await db.commit()
            logger.info("批量任务已完成: %s", job_uuid)

    except Exception:
        logger.exception("批量任务执行异常: %s", job_uuid)
        # 标记为 completed（带错误）
        try:
            await db.execute(
                "UPDATE batch_jobs SET status = 'completed', completed_at = datetime('now','localtime') WHERE uuid = ?",
                (job_uuid,),
            )
            await db.commit()
        except Exception:
            logger.warning("批量任务状态更新失败 (二次异常): %s", job_uuid, exc_info=True)
    finally:
        _running_tasks.pop(job_uuid, None)


async def pause_batch_job(job_uuid: str) -> dict:
    """将 job status 设为 paused。"""
    db = get_db()
    async with db.execute("SELECT status FROM batch_jobs WHERE uuid = ?", (job_uuid,)) as cursor:
        row = await cursor.fetchone()
    if not row:
        return {"error": "任务不存在"}
    if row[0] != "running":
        return {"error": f"当前状态 {row[0]} 不可暂停"}

    await db.execute(
        "UPDATE batch_jobs SET status = 'paused' WHERE uuid = ?",
        (job_uuid,),
    )
    await db.commit()
    logger.info("批量任务已暂停: %s", job_uuid)
    return {"uuid": job_uuid, "status": "paused"}


async def resume_batch_job(job_uuid: str) -> dict:
    """将 job status 设为 running，重新启动 run_batch_job。"""
    db = get_db()
    async with db.execute("SELECT status FROM batch_jobs WHERE uuid = ?", (job_uuid,)) as cursor:
        row = await cursor.fetchone()
    if not row:
        return {"error": "任务不存在"}
    if row[0] not in ("paused", "interrupted"):
        return {"error": f"当前状态 {row[0]} 不可恢复"}

    await db.execute(
        "UPDATE batch_jobs SET status = 'running' WHERE uuid = ?",
        (job_uuid,),
    )
    # 将中断时处于 running 状态的 items 重置为 pending
    await db.execute(
        """UPDATE batch_job_items SET status = 'pending', started_at = NULL
           WHERE job_id = (SELECT id FROM batch_jobs WHERE uuid = ?)
             AND status = 'running'""",
        (job_uuid,),
    )
    await db.commit()

    # 重新启动异步执行
    task = asyncio.create_task(run_batch_job(job_uuid))
    _running_tasks[job_uuid] = task

    logger.info("批量任务已恢复: %s", job_uuid)
    return {"uuid": job_uuid, "status": "running"}


async def cancel_batch_job(job_uuid: str) -> dict:
    """将 job status 设为 cancelled。"""
    db = get_db()
    async with db.execute("SELECT status FROM batch_jobs WHERE uuid = ?", (job_uuid,)) as cursor:
        row = await cursor.fetchone()
    if not row:
        return {"error": "任务不存在"}
    if row[0] in ("completed", "cancelled"):
        return {"error": f"当前状态 {row[0]} 不可取消"}

    await db.execute(
        "UPDATE batch_jobs SET status = 'cancelled', completed_at = datetime('now','localtime') WHERE uuid = ?",
        (job_uuid,),
    )
    await db.commit()
    logger.info("批量任务已取消: %s", job_uuid)
    return {"uuid": job_uuid, "status": "cancelled"}


async def get_batch_jobs(status: str | None = None, page: int = 1, limit: int = 20) -> dict:
    """获取任务列表（支持分页和状态过滤）。"""
    db = get_db()
    offset = (page - 1) * limit

    where_clause = ""
    params: list = []
    if status:
        where_clause = "WHERE status = ?"
        params.append(status)

    # 查询总数
    async with db.execute(
        f"SELECT COUNT(*) FROM batch_jobs {where_clause}",
        params,
    ) as cursor:
        total = (await cursor.fetchone())[0]

    # 查询列表
    async with db.execute(
        f"""SELECT id, uuid, status, document_count, handlers, total_items,
                   success_count, failed_count, skipped_count,
                   created_at, started_at, completed_at
            FROM batch_jobs {where_clause}
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?""",
        params + [limit, offset],
    ) as cursor:
        rows = await cursor.fetchall()

    items = []
    for row in rows:
        handlers_data = []
        if row[3]:
            try:
                handlers_data = json.loads(row[3]) if isinstance(row[3], str) else row[3]
            except (json.JSONDecodeError, TypeError):
                pass

        items.append(
            {
                "id": row[0],
                "uuid": row[1],
                "status": row[2],
                "document_count": row[3],
                "handlers": handlers_data,
                "total_items": row[5],
                "success_count": row[6],
                "failed_count": row[7],
                "skipped_count": row[8],
                "created_at": row[9],
                "started_at": row[10],
                "completed_at": row[11],
            }
        )

    return {"items": items, "total": total, "page": page}


async def get_batch_job_detail(job_uuid: str) -> dict | None:
    """
    获取任务详情。

    - per-handler 统计: 按 (plugin_name, handler_name) GROUP BY
    - skipped per handler = document_count - 该handler在items中的记录数
    - 失败项列表: LEFT JOIN documents 获取 file_name
    """
    db = get_db()

    # 查询 job 基础信息
    async with db.execute(
        """SELECT id, uuid, status, document_count, handlers, total_items,
                  success_count, failed_count, skipped_count,
                  created_at, started_at, completed_at
           FROM batch_jobs WHERE uuid = ?""",
        (job_uuid,),
    ) as cursor:
        job_row = await cursor.fetchone()

    if not job_row:
        return None

    job_id = job_row[0]
    document_count = job_row[3]
    handlers_data = []
    if job_row[4]:
        try:
            handlers_data = json.loads(job_row[4]) if isinstance(job_row[4], str) else job_row[4]
        except (json.JSONDecodeError, TypeError):
            pass

    result = {
        "uuid": job_row[1],
        "status": job_row[2],
        "document_count": document_count,
        "handlers": handlers_data,
        "total_items": job_row[5],
        "success_count": job_row[6],
        "failed_count": job_row[7],
        "skipped_count": job_row[8],
        "created_at": job_row[9],
        "started_at": job_row[10],
        "completed_at": job_row[11],
    }

    # per-handler 统计
    async with db.execute(
        """SELECT bi.plugin_name, bi.handler_name,
                  COUNT(*) as total,
                  SUM(CASE WHEN bi.status = 'success' THEN 1 ELSE 0 END) as success,
                  SUM(CASE WHEN bi.status = 'failed' THEN 1 ELSE 0 END) as failed
           FROM batch_job_items bi
           WHERE bi.job_id = ?
           GROUP BY bi.plugin_name, bi.handler_name""",
        (job_id,),
    ) as cursor:
        handler_stats_rows = await cursor.fetchall()

    # 从 PluginManager 获取 handler 额外信息
    manager = get_plugin_manager()
    handler_stats = []
    for stat_row in handler_stats_rows:
        pname, hname, total, success, failed = stat_row
        handler_info = manager.get_handler_info(pname, hname)
        handler_stats.append(
            {
                "plugin_name": pname,
                "handler_name": hname,
                "handler_type": handler_info.handler_type.value if handler_info else "",
                "description": handler_info.description if handler_info else "",
                "total": total,
                "success": success,
                "failed": failed,
                "skipped": document_count - total,
            }
        )
    result["handler_stats"] = handler_stats

    # 失败项列表
    async with db.execute(
        """SELECT bi.document_id, d.file_name, bi.plugin_name, bi.handler_name, bi.error_message
           FROM batch_job_items bi
           LEFT JOIN documents d ON bi.document_id = d.id
           WHERE bi.job_id = ? AND bi.status = 'failed'
           ORDER BY bi.id""",
        (job_id,),
    ) as cursor:
        failed_rows = await cursor.fetchall()

    result["failed_items"] = [
        {
            "document_id": r[0],
            "file_name": r[1] or f"(已删除, id={r[0]})",
            "plugin_name": r[2],
            "handler_name": r[3],
            "error_message": r[4],
        }
        for r in failed_rows
    ]

    return result


async def mark_interrupted_jobs() -> None:
    """启动时将 running 状态的任务标记为 interrupted；paused 任务保持不变，用户可手动恢复。"""
    db = get_db()
    await db.execute(
        """UPDATE batch_jobs
           SET status = 'interrupted', completed_at = datetime('now','localtime')
           WHERE status = 'running'""",
    )
    await db.commit()
    logger.info("已将中断的批量任务标记为 interrupted")
