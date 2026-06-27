"""文档摄取服务 — 文件入库前置逻辑。

本模块涵盖文档从"接收"到"入库"的前置流程：
  - 哈希计算、去重检查、路径验证、文件保存、DB 记录创建/更新
"""

import hashlib
import logging
import uuid as uuid_module
from pathlib import Path

import aiosqlite

from app.config import get_settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 接收阶段：文件入库前置逻辑
# ---------------------------------------------------------------------------


def compute_file_hash(file_path: Path) -> str:
    """
    计算文件的 SHA256 哈希值。

    Args:
        file_path: 文件路径

    Returns:
        SHA256 哈希值（64 位十六进制字符串）
    """
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(8192):
            sha256.update(chunk)
    return sha256.hexdigest()


async def check_duplicate(db: aiosqlite.Connection, file_hash: str) -> dict | None:
    """
    检查文件是否已存在（通过 file_hash）。

    Args:
        db: 数据库连接
        file_hash: 文件的 SHA256 哈希值

    Returns:
        如果已存在返回 {"uuid": existing_uuid}，否则返回 None
    """
    async with db.execute("SELECT uuid FROM documents WHERE file_hash = ?", (file_hash,)) as cursor:
        row = await cursor.fetchone()
        if row:
            return {"uuid": row[0]}
    return None


def validate_import_path(raw_path: str) -> Path:
    """
    验证导入路径的安全性。

    Args:
        raw_path: 原始路径字符串

    Returns:
        验证通过的 Path 对象

    Raises:
        ValueError: 路径不存在、不是目录、或不在白名单范围内
    """
    settings = get_settings()

    # 消除 ../ 穿越
    path = Path(raw_path).resolve()

    # 检查路径是否存在
    if not path.exists():
        raise ValueError("路径不存在")

    # 检查是否为目录
    if not path.is_dir():
        raise ValueError("路径必须是目录")

    # 检查白名单
    whitelist = settings.IMPORT_DIR_WHITELIST
    if whitelist:
        if not any(path == w or path.is_relative_to(w) for w in whitelist):
            raise ValueError("路径不在允许的导入目录范围内")

    return path


def save_uploaded_file(file_content: bytes, original_filename: str, library_root: Path) -> tuple[Path, str]:
    """
    保存上传的文件。

    Args:
        file_content: 文件内容
        original_filename: 原始文件名
        library_root: 文件库根目录

    Returns:
        (saved_path, uuid_str) - 保存路径和生成的 UUID
    """
    # 生成 UUID
    uuid_str = str(uuid_module.uuid4())

    # 提取文件扩展名
    extension = Path(original_filename).suffix.lower()
    if extension.startswith("."):
        extension = extension[1:]

    # 确保目录存在
    library_root.mkdir(parents=True, exist_ok=True)

    # 保存文件
    saved_path = library_root / f"{uuid_str}.{extension}"
    saved_path.write_bytes(file_content)

    logger.debug("文件已保存: %s", saved_path)

    return (saved_path, uuid_str)


async def upsert_document_by_path(
    db: aiosqlite.Connection,
    file_name: str,
    file_path: str,
    source_dir: str,
    import_method: str,
    file_type: str,
    file_size: int,
    file_hash: str,
    file_modified_time: str,
    uuid: str | None = None,
) -> tuple[int, str, bool]:
    """
    根据 file_path 查找或创建文档记录。

    如果 file_path 已存在，则更新相关字段（保持 ID 和 UUID 不变）。
    如果 file_path 不存在，则创建新记录。

    Args:
        db: 数据库连接
        file_name: 原始文件名
        file_path: 文件存储路径
        source_dir: 来源目录
        import_method: 导入方式 ('upload' | 'directory')
        file_type: 文件类型（不带点，如 'pdf'）
        file_size: 文件大小（字节）
        file_hash: 文件 SHA256 哈希
        file_modified_time: 文件修改时间

    Returns:
        (document_id, uuid, is_update) - 文档 ID、UUID、是否为更新操作
    """
    # 检查 file_path 是否已存在
    async with db.execute("SELECT id, uuid FROM documents WHERE file_path = ?", (file_path,)) as cursor:
        row = await cursor.fetchone()

    if row:
        # 文件路径已存在，更新记录
        document_id, uuid = row
        await db.execute(
            """
            UPDATE documents
            SET file_name = ?, file_type = ?, file_size = ?,
                file_hash = ?, file_modified_time = ?
            WHERE id = ?
            """,
            (
                file_name,
                file_type,
                file_size,
                file_hash,
                file_modified_time,
                document_id,
            ),
        )
        await db.commit()
        logger.info(
            "文档记录已更新: id=%d, uuid=%s, path=%s",
            document_id,
            uuid,
            file_path,
        )
        return (document_id, uuid, True)
    else:
        # 文件路径不存在，创建新记录
        import uuid as uuid_mod

        if uuid is None:
            uuid = str(uuid_mod.uuid4())
        async with db.execute(
            """
            INSERT INTO documents (
                uuid, file_name, file_path, source_dir, import_method,
                file_type, file_size, file_hash, file_modified_time
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                uuid,
                file_name,
                file_path,
                source_dir,
                import_method,
                file_type,
                file_size,
                file_hash,
                file_modified_time,
            ),
        ) as cursor:
            document_id = cursor.lastrowid

        await db.commit()
        logger.info(
            "文档记录已创建: uuid=%s, id=%d, path=%s",
            uuid,
            document_id,
            file_path,
        )
        return (document_id, uuid, False)
