"""文档管理 API — HTTP 协议层，业务逻辑委托给服务层。"""

import asyncio
import hashlib
import logging
import mimetypes
import tempfile
import uuid as uuid_module
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from litestar import Request, Response, Router, delete, get, patch, post
from litestar.datastructures import UploadFile
from litestar.enums import RequestEncodingType
from litestar.exceptions import HTTPException
from litestar.params import Body
from litestar.response import File, Template
from litestar.status_codes import (
    HTTP_204_NO_CONTENT,
    HTTP_400_BAD_REQUEST,
    HTTP_404_NOT_FOUND,
    HTTP_409_CONFLICT,
    HTTP_422_UNPROCESSABLE_ENTITY,
)

from app.config import get_settings
from app.database import get_db
from app.services.documents import (
    list_documents_service,
    get_document_service,
    update_document_fields,
    replace_document_tags,
    add_document_tags,
    remove_document_tag_service,
    batch_delete_documents_service,
    batch_add_tags_service,
    build_plugin_context,
    update_document_thumbnail,
)
from app.services.batch_jobs import create_pipeline_batch_job
from app.services.ingestion import (
    check_duplicate,
    upsert_document_by_path,
    validate_import_path,
    compute_file_hash,
)
from app.plugins.core import PreviewResult, TaskHandlerType
from app.plugins.manager import get_plugin_manager

logger = logging.getLogger(__name__)


@get("/documents")
async def list_documents(
    page: int = 1,
    limit: int = 20,
    type: str | None = None,
    tag: str | None = None,
    sort: str | None = None,
) -> dict:
    """
    文档列表（offset 分页）。

    使用页码分页，返回 page/total_pages/total_count。
    支持排序：default / name_asc / name_desc / size_asc / size_desc / date_asc / date_desc。
    """
    documents, current_page, total_pages, total_count = await list_documents_service(
        page=page, limit=limit, file_type=type, tag=tag, sort=sort,
    )
    return {
        "documents": documents,
        "page": current_page,
        "total_pages": total_pages,
        "total_count": total_count,
    }


@get("/documents/{uuid:str}")
async def get_document(uuid: str) -> dict:
    """获取单条文档元数据，包含标签、文本信息和可用格式列表。"""
    doc = await get_document_service(uuid)
    if doc is None:
        raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail="文档不存在")

    # 获取可用格式列表
    manager = get_plugin_manager()
    file_type = doc.get("file_type", "")
    doc["preview_formats"] = manager.get_preview_formats(file_type)
    doc["download_formats"] = manager.get_download_formats(file_type)

    return doc


@post("/upload")
async def upload_file(
    data: UploadFile = Body(media_type=RequestEncodingType.MULTI_PART),
) -> dict:
    """
    上传文件（multipart/form-data）。

    流程：
    1. 校验文件后缀
    2. 读取文件内容
    3. 计算 SHA256 去重
    4. 保存文件
    5. 创建文档记录和导入任务
    6. 返回响应后启动后台处理
    """
    settings = get_settings()
    db = get_db()

    # 获取原始文件名
    original_filename = data.filename
    if not original_filename:
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST, detail="文件名不能为空"
        )

    # 1. 校验文件后缀
    extension = Path(original_filename).suffix.lower()
    if extension not in settings.ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail=f"不支持的文件类型: {extension}",
        )

    # 2. 流式写入临时文件并计算哈希（避免大文件全量驻留内存）
    settings.LIBRARY_ROOT.mkdir(parents=True, exist_ok=True)
    tmp_fd = tempfile.NamedTemporaryFile(
        delete=False, dir=str(settings.LIBRARY_ROOT), suffix=extension
    )
    tmp_path = Path(tmp_fd.name)
    try:
        sha256 = hashlib.sha256()
        file_size = 0
        while chunk := await data.read(8192):
            sha256.update(chunk)
            tmp_fd.write(chunk)
            file_size += len(chunk)
        tmp_fd.close()
        file_hash = sha256.hexdigest()

        # 3. 查重
        existing = await check_duplicate(db, file_hash)
        if existing:
            tmp_path.unlink(missing_ok=True)
            raise HTTPException(
                status_code=HTTP_409_CONFLICT,
                detail="文件已存在",
                extra={"existing_uuid": existing["uuid"]},
            )

        # 4. 重命名为最终路径 (uuid.ext)
        uuid_str = str(uuid_module.uuid4())
        file_type = extension[1:] if extension.startswith(".") else extension
        final_path = settings.LIBRARY_ROOT / f"{uuid_str}.{file_type}"
        tmp_path.rename(final_path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise

    # 获取修改时间
    file_modified_time = datetime.now().isoformat()

    # 5. 查找或创建文档记录（基于 file_path）
    document_id, db_uuid, is_update = await upsert_document_by_path(
        db=db,
        file_name=original_filename,
        file_path=final_path.name,
        source_dir=str(settings.LIBRARY_ROOT),
        import_method="upload",
        file_type=file_type,
        file_size=file_size,
        file_hash=file_hash,
        file_modified_time=file_modified_time,
        uuid=uuid_str,
    )

    # 7. 提交后台批量处理任务
    batch_job = await create_pipeline_batch_job([db_uuid])

    # 8. 返回响应
    return {
        "uuid": uuid_str,
        "message": "文件导入成功，处理任务已提交，请前往任务列表查看进度",
        "batch_job": batch_job,
    }


@get("/import-directory")
async def import_directory(path: str) -> dict:
    """
    导入本地目录中的支持文件。

    扫描目录后将文件入库，并为所有成功导入的文档自动提交批量处理任务。
    返回导入统计信息及批量任务详情，前端可前往任务列表查看处理进度。
    """
    settings = get_settings()
    db = get_db()

    if not path:
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail="path 参数不能为空",
        )

    # 安全校验
    try:
        validated_path = validate_import_path(path)
    except ValueError:
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail="路径不合法",
        )

    # 扫描目录，收集所有支持的文件
    files = [
        f for f in validated_path.rglob("*")
        if f.is_file() and f.suffix.lower() in settings.ALLOWED_EXTENSIONS
    ]
    total = len(files)

    imported_count = 0
    skipped_count = 0
    failed_count = 0
    imported_uuids: list[str] = []

    for file_path in files:
        file_name = file_path.name
        extension = file_path.suffix.lower()

        try:
            # 计算 SHA256 去重
            file_hash = await asyncio.to_thread(compute_file_hash, file_path)

            # 检查是否已存在
            existing = await check_duplicate(db, file_hash)
            if existing:
                skipped_count += 1
            else:
                file_type = extension[1:] if extension.startswith(".") else extension
                file_stat = file_path.stat()
                file_size = file_stat.st_size
                file_modified_time = datetime.fromtimestamp(file_stat.st_mtime).isoformat()
                file_path_str = str(file_path.resolve())

                document_id, uuid_str, is_update = await upsert_document_by_path(
                    db=db,
                    file_name=file_name,
                    file_path=file_path_str,
                    source_dir=str(validated_path),
                    import_method="directory",
                    file_type=file_type,
                    file_size=file_size,
                    file_hash=file_hash,
                    file_modified_time=file_modified_time,
                )

                imported_uuids.append(uuid_str)
                imported_count += 1
                logger.info("目录导入文件: %s, uuid=%s", file_path, uuid_str)

        except Exception as e:
            failed_count += 1
            logger.warning("目录导入失败: %s, error=%s", file_path, e)

    # 为成功导入的文档自动创建批量处理任务
    batch_job = None
    if imported_uuids:
        batch_job = await create_pipeline_batch_job(imported_uuids)

    return {
        "total": total,
        "imported_count": imported_count,
        "skipped_count": skipped_count,
        "failed_count": failed_count,
        "batch_job": batch_job,
        "message": (
            f"已导入 {imported_count} 个文件，"
            f"跳过 {skipped_count} 个重复文件，"
            f"失败 {failed_count} 个。"
            f"处理任务已提交，请前往任务列表查看进度。"
        ),
    }


@patch("/documents/{uuid:str}")
async def update_document(uuid: str, data: dict) -> dict:
    """
    更新文档标题和/或标签。

    data 可包含：
    - title: 新标题
    - tag_uuids: 标签 UUID 列表（会先删除旧关联再插入新关联）
    - add_tags: 标签名称列表（增量添加，自动创建不存在的标签）
    """
    try:
        # 可编辑字段更新（title, authors, summary, meta_data）
        editable_keys = {"title", "authors", "summary", "meta_data"}
        field_updates = {k: v for k, v in data.items() if k in editable_keys}
        if field_updates:
            await update_document_fields(uuid, field_updates)

        if "tag_uuids" in data:
            await replace_document_tags(uuid, data["tag_uuids"])
        if "add_tags" in data:
            await add_document_tags(uuid, data["add_tags"])
    except ValueError as e:
        raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail=str(e))

    # 返回更新后的文档
    doc = await get_document_service(uuid)
    if doc is None:
        raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail="文档不存在")
    return doc


@post("/documents/{uuid:str}/thumbnail")
async def upload_document_thumbnail(
    uuid: str,
    data: UploadFile = Body(media_type=RequestEncodingType.MULTI_PART),
) -> dict:
    """
    上传自定义缩略图（multipart/form-data）。

    仅支持图片文件，处理为标准 JPEG 缩略图后保存。
    """
    settings = get_settings()

    # 校验文件名
    filename = data.filename or ""
    if not filename:
        raise HTTPException(status_code=HTTP_400_BAD_REQUEST, detail="文件名不能为空")

    # 校验文件类型（通过后缀判断）
    extension = Path(filename).suffix.lower()
    if extension not in settings.IMAGE_EXTENSIONS:
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail=f"不支持的文件类型: {extension}，仅支持图片文件",
        )

    # 读取文件内容
    file_bytes = await data.read()
    if not file_bytes:
        raise HTTPException(status_code=HTTP_400_BAD_REQUEST, detail="文件内容为空")

    # 处理并保存缩略图
    try:
        await update_document_thumbnail(uuid, file_bytes)
    except ValueError as e:
        raise HTTPException(status_code=HTTP_400_BAD_REQUEST, detail=str(e))

    # 返回更新后的文档详情
    doc = await get_document_service(uuid)
    if doc is None:
        raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail="文档不存在")

    # 补充格式列表
    manager = get_plugin_manager()
    file_type = doc.get("file_type", "")
    doc["preview_formats"] = manager.get_preview_formats(file_type)
    doc["download_formats"] = manager.get_download_formats(file_type)

    return doc


@post("/documents/batch-delete")
async def batch_delete_documents(data: dict) -> dict:
    """
    批量删除文档记录。

    仅删除数据库记录，不删除源文件。
    CASCADE 会自动清理 document_tags 和 document_texts。
    """
    uuids = data.get("uuids", [])
    if not uuids or not isinstance(uuids, list):
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST, detail="请提供要删除的文档 UUID 列表"
        )

    try:
        deleted_count = await batch_delete_documents_service(uuids)
    except ValueError as e:
        raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail=str(e))

    return {"deleted_count": deleted_count}


@post("/documents/batch-add-tags")
async def batch_add_tags(data: dict) -> dict:
    """
    批量为多个文档添加标签。

    data 包含：
    - uuids: 文档 UUID 列表
    - tag_names: 标签名称列表（自动创建不存在的标签）
    """
    uuids = data.get("uuids", [])
    tag_names = data.get("tag_names", [])

    if not uuids or not isinstance(uuids, list):
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST, detail="请提供要操作的文档 UUID 列表"
        )
    if not tag_names or not isinstance(tag_names, list):
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST, detail="请提供要添加的标签名称列表"
        )

    try:
        processed = await batch_add_tags_service(uuids, tag_names)
    except ValueError as e:
        raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail=str(e))

    return {"processed_count": processed}


@delete("/documents/{uuid:str}/tags/{tag_uuid:str}", status_code=HTTP_204_NO_CONTENT)
async def remove_document_tag(uuid: str, tag_uuid: str) -> None:
    """从文档中移除指定标签。"""
    try:
        await remove_document_tag_service(uuid, tag_uuid)
    except ValueError as e:
        raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail=str(e))


@get("/documents/{uuid:str}/download")
async def download_document(uuid: str, request: Request, inline: bool = False, target_type: str | None = None) -> File | Response:
    """
    下载原始文件，支持 HTTP Range 请求。
    
    返回文件响应，Content-Disposition 使用原始文件名。
    """
    try:
        ctx = await build_plugin_context(uuid)
    except ValueError as e:
        raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail=str(e))

    file_path = ctx.file_path
    file_name = ctx.file_name
    file_type = ctx.file_type

    # 如果指定了 target_type 且与原格式不同，执行格式转换
    if target_type and target_type != file_type:
        manager = get_plugin_manager()
        convert_handler = manager.find_handler(TaskHandlerType.CONVERT, file_type)
        if convert_handler is None:
            raise HTTPException(
                status_code=HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"不支持 {file_type} 的格式转换",
            )

        ctx.target_type = target_type
        convert_result = await asyncio.to_thread(
            manager.execute, convert_handler.plugin.name, convert_handler.info.handler_name, ctx
        )
        if convert_result is None:
            raise HTTPException(
                status_code=HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"不支持转换为 {target_type} 格式",
            )

        converted_bytes = convert_result.content

        converted_filename = Path(file_name).stem + f".{target_type}"
        media_type = mimetypes.guess_type(converted_filename)[0] or "application/octet-stream"

        # RFC 5987: 非 ASCII 文件名需要用 filename* 参数编码
        try:
            converted_filename.encode("ascii")
            disposition = f'attachment; filename="{converted_filename}"'
        except UnicodeEncodeError:
            encoded_name = quote(converted_filename)
            disposition = f"attachment; filename*=UTF-8''{encoded_name}"

        return Response(
            content=converted_bytes,
            media_type=media_type,
            headers={
                "Content-Disposition": disposition,
            },
        )

    # 检查 Range 请求
    range_header = request.headers.get("range")
    if range_header and range_header.startswith("bytes="):
        file_size = file_path.stat().st_size
        
        # 解析 Range header
        range_spec = range_header[6:].strip()  # 移除 "bytes="
        
        # 确定 content type
        content_type = mimetypes.guess_type(file_name)[0] or "application/octet-stream"
        
        try:
            if range_spec.startswith("-"):
                # bytes=-N (最后 N 字节)
                suffix_len = int(range_spec[1:])
                start = max(0, file_size - suffix_len)
                end = file_size - 1
            elif range_spec.endswith("-"):
                # bytes=N- (从 N 到末尾)
                start = int(range_spec[:-1])
                end = file_size - 1
            else:
                # bytes=N-M
                parts = range_spec.split("-", 1)
                start = int(parts[0])
                end = int(parts[1])
            
            # 验证范围
            if start < 0 or start >= file_size or end < start:
                return Response(
                    content=b"",
                    status_code=416,
                    headers={
                        "Content-Range": f"bytes */{file_size}",
                        "Accept-Ranges": "bytes",
                    },
                )
            
            end = min(end, file_size - 1)
            content_length = end - start + 1
            
            # 读取指定范围
            with open(file_path, "rb") as f:
                f.seek(start)
                data = f.read(content_length)
            
            disposition = "inline" if inline else "attachment"
            
            return Response(
                content=data,
                status_code=206,
                headers={
                    "Content-Type": content_type,
                    "Content-Range": f"bytes {start}-{end}/{file_size}",
                    "Content-Length": str(content_length),
                    "Accept-Ranges": "bytes",
                    "Content-Disposition": f'{disposition}; filename="{file_name}"',
                },
            )
        except (ValueError, OSError) as e:
            logger.debug("Range 解析失败，回退到完整文件返回: %s", e)
    
    # 无 Range 或解析失败 → 返回完整文件
    logger.info("下载文件: uuid=%s, file_name=%s", uuid, file_name)
    
    return File(
        path=file_path,
        filename=file_name,
        content_disposition_type="inline" if inline else "attachment",
        headers={"Accept-Ranges": "bytes"},
    )


@get("/documents/{uuid:str}/preview")
async def preview_document(uuid: str, target_type: str | None = None) -> File | Template | Response:
    """
    预览文档。

    通过插件系统分发预览，支持可选的格式转换。
    """
    settings = get_settings()
    manager = get_plugin_manager()

    try:
        ctx = await build_plugin_context(uuid)
    except ValueError as e:
        raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail=str(e))

    file_name = ctx.file_name
    file_type = ctx.file_type

    # 预览逻辑
    tmp_path = None  # 格式转换产生的临时文件路径
    preview_type = file_type  # 默认用原格式的 preview 插件

    # 当原格式没有可用的预览handler且用户未指定target_type时，
    # 尝试自动选择第一个可用的转换目标格式进行回退预览
    if not target_type and not manager.find_handler(TaskHandlerType.PREVIEW, file_type):
        available_formats = manager.get_preview_formats(file_type)
        for fmt in available_formats:
            if fmt != file_type:
                target_type = fmt
                logger.info("原格式预览不可用，自动回退: %s -> %s", file_type, target_type)
                break

    if target_type and target_type != file_type:
        # 需要先转换格式
        convert_handler = manager.find_handler(TaskHandlerType.CONVERT, file_type)
        if convert_handler:
            try:
                ctx.target_type = target_type
                convert_result = await asyncio.to_thread(
                    manager.execute, convert_handler.plugin.name, convert_handler.info.handler_name, ctx
                )
                if convert_result is not None:
                    converted_bytes = convert_result.content
                    preview_type = target_type
                    ctx.file_type = target_type  # 确保 preview 阶段解析到正确的插件
                    # 保存为临时文件，更新 ctx.file_path
                    import tempfile
                    previews_dir = settings.PREVIEWS_ROOT
                    previews_dir.mkdir(parents=True, exist_ok=True)
                    tmp = tempfile.NamedTemporaryFile(
                        suffix=f".{target_type}", delete=False,
                        dir=str(previews_dir),
                    )
                    tmp.write(converted_bytes)
                    tmp.close()
                    tmp_path = Path(tmp.name)
                    ctx.file_path = tmp_path
                    ctx.file_name = Path(ctx.file_name).stem + f".{target_type}"
                    ctx.file_url = f"/previews/{tmp_path.name}"
                else:
                    logger.warning("转换失败: %s -> %s", file_type, target_type)
            except Exception as e:
                logger.warning("转换异常: %s -> %s, error=%s", file_type, target_type, e)

    # 无转换时，使用下载接口作为 file_url
    if not ctx.file_url:
        ctx.file_url = f"/api/documents/{uuid}/download?inline=true"

    preview_handler = manager.find_handler(TaskHandlerType.PREVIEW, preview_type)
    if preview_handler:
        try:
            result = await asyncio.to_thread(
                manager.execute, preview_handler.plugin.name, preview_handler.info.handler_name, ctx
            )
        except Exception as e:
            logger.warning("预览失败: file_type=%s, error=%s", preview_type, e)
            result = None
    else:
        result = None

    # 如果目标格式不同于原格式，且原格式没有匹配到 preview 插件，
    # 尝试用 target_type 的 preview 插件
    if result is None and target_type and target_type != file_type and tmp_path is not None:
        fallback_handler = manager.find_handler(TaskHandlerType.PREVIEW, target_type)
        if fallback_handler:
            try:
                result = await asyncio.to_thread(
                    manager.execute, fallback_handler.plugin.name, fallback_handler.info.handler_name, ctx
                )
            except Exception as e:
                logger.warning("目标格式预览失败: target_type=%s, error=%s", target_type, e)

    # 处理返回结果
    if result is not None:
        # 如果 result 是 PreviewResult 对象
        if isinstance(result, PreviewResult):
            if result.is_html():
                return Response(content=result.html, media_type="text/html")
            elif result.is_file():
                return File(
                    path=result.file_path,
                    filename=result.file_path.name,
                    content_disposition_type="inline",
                )
        # 如果 result 是字符串（向后兼容，视为 HTML）
        elif isinstance(result, str):
            return Response(content=result, media_type="text/html")

    # 无插件命中或预览失败 → 返回不支持模板
    ext = f".{file_type}" if not file_type.startswith(".") else file_type
    return Template(
        template_name="preview_unsupported.html",
        context={"file_name": file_name, "file_type": ext},
    )


# 路由器
documents_router = Router(
    path="/api",
    route_handlers=[
        list_documents,
        get_document,
        upload_file,
        import_directory,
        update_document,
        upload_document_thumbnail,
        batch_delete_documents,
        batch_add_tags,
        remove_document_tag,
        download_document,
        preview_document,
    ],
)

