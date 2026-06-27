"""Litestar 应用入口 - 整合所有模块。"""

import contextvars
import hashlib
import hmac
import json as _json
import logging
import time
import uuid as uuid_mod
from logging.handlers import RotatingFileHandler
from pathlib import Path

from litestar import Litestar, Request, get, post
from litestar.contrib.jinja import JinjaTemplateEngine
from litestar.datastructures import Cookie
from litestar.exceptions import HTTPException
from litestar.middleware.base import AbstractMiddleware
from litestar.response import File, Redirect, Template
from litestar.static_files import create_static_files_router
from litestar.status_codes import HTTP_404_NOT_FOUND
from litestar.template.config import TemplateConfig
from litestar.types import Receive, Scope, Send

from app.api.batch_jobs import BatchJobController
from app.api.documents import documents_router
from app.api.plugins import plugins_router
from app.api.search import search_router
from app.api.settings import settings_router
from app.api.tags import tags_router
from app.config import get_settings, load_settings_from_db
from app.database import close_db, get_db, init_db
from app.plugins.manager import PluginManager, set_plugin_manager

logger = logging.getLogger(__name__)

# 项目根目录（app 目录）
BASE_DIR = Path(__file__).resolve().parent

# 项目根目录（app 的上级目录，用于静态文件）
PROJECT_ROOT = BASE_DIR.parent


# ──────────────────────────────────────────
#  认证相关
# ──────────────────────────────────────────


def _sign_cookie(value: str, secret: str) -> str:
    """生成 value.signature 格式的签名 Cookie。"""
    sig = hmac.new(secret.encode(), value.encode(), hashlib.sha256).hexdigest()
    return f"{value}.{sig}"


def _verify_cookie(cookie: str, secret: str) -> bool:
    """验证签名 Cookie 是否有效。"""
    if "." not in cookie:
        return False
    value, sig = cookie.rsplit(".", 1)
    expected = hmac.new(secret.encode(), value.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig, expected)


# 认证白名单路径前缀
_AUTH_WHITELIST = ("/login", "/api/login", "/static/")


class AuthMiddleware(AbstractMiddleware):
    """极简登录门禁中间件：未认证请求重定向到 /login 或返回 401。"""

    scopes = {"http"}

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        settings = get_settings()
        # 未配置密码，不启用认证
        if not settings.AUTH_PASSWORD:
            await self.app(scope, receive, send)
            return

        path: str = scope.get("path", "")

        # 白名单放行
        if any(path.startswith(prefix) for prefix in _AUTH_WHITELIST):
            await self.app(scope, receive, send)
            return

        # 解析 Cookie
        headers = dict(scope.get("headers", []))
        cookie_header = headers.get(b"cookie", b"").decode("utf-8", errors="replace")
        cookies = {}
        for item in cookie_header.split(";"):
            item = item.strip()
            if "=" in item:
                k, v = item.split("=", 1)
                cookies[k.strip()] = v.strip()

        token = cookies.get(settings.AUTH_COOKIE_NAME, "")
        if _verify_cookie(token, settings.AUTH_SECRET_KEY):
            await self.app(scope, receive, send)
            return

        # 未认证：区分页面请求和 API 请求
        accept = headers.get(b"accept", b"").decode("utf-8", errors="replace")
        if "text/html" in accept:
            # 页面请求 → 302 重定向到 /login
            await send(
                {
                    "type": "http.response.start",
                    "status": 302,
                    "headers": [
                        (b"location", b"/login"),
                        (b"content-length", b"0"),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": b""})
        else:
            # API 请求 → 401 JSON
            body = _json.dumps({"detail": "未登录"}).encode()
            await send(
                {
                    "type": "http.response.start",
                    "status": 401,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(body)).encode()),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})


@get("/login")
async def login_page(request: Request) -> Template:
    """登录页面。"""
    error = request.query_params.get("error", "")
    return Template(template_name="login.html", context={"error": error})


@post("/api/login")
async def login_action(request: Request) -> Redirect:
    """校验密码并签发 Cookie。"""
    settings = get_settings()
    form_data = await request.form()
    password = form_data.get("password", "")

    if not hmac.compare_digest(str(password), settings.AUTH_PASSWORD):
        return Redirect(path="/login?error=1")

    # 签发 Cookie
    token_value = uuid_mod.uuid4().hex
    signed = _sign_cookie(token_value, settings.AUTH_SECRET_KEY)
    response = Redirect(path="/")
    response.cookies.append(
        Cookie(
            key=settings.AUTH_COOKIE_NAME,
            value=signed,
            max_age=settings.AUTH_MAX_AGE,
            httponly=True,
            path="/",
            samesite="lax",
        )
    )
    return response


@post("/api/logout")
async def logout_action() -> Redirect:
    """清除会话 Cookie。"""
    settings = get_settings()
    response = Redirect(path="/login")
    response.cookies.append(
        Cookie(
            key=settings.AUTH_COOKIE_NAME,
            value="",
            max_age=0,
            httponly=True,
            path="/",
        )
    )
    return response


@get("/")
async def index() -> Template:
    """首页路由。"""
    settings = get_settings()
    extension_map = {
        "document": sorted(ext.lstrip(".") for ext in settings.DOCUMENT_EXTENSIONS),
        "ebook": sorted(ext.lstrip(".") for ext in settings.EBOOK_EXTENSIONS),
        "text": sorted(ext.lstrip(".") for ext in settings.TEXT_EXTENSIONS),
        "image": sorted(ext.lstrip(".") for ext in settings.IMAGE_EXTENSIONS),
        "audio": sorted(ext.lstrip(".") for ext in settings.AUDIO_EXTENSIONS),
        "video": sorted(ext.lstrip(".") for ext in settings.VIDEO_EXTENSIONS),
        "archive": sorted(ext.lstrip(".") for ext in settings.ARCHIVE_EXTENSIONS),
    }
    return Template(template_name="index.html", context={"extension_map": extension_map})


@get("/import")
async def import_page() -> Template:
    """导入页面。"""
    return Template(template_name="import.html")


@get("/settings")
async def settings_page() -> Template:
    """设置中心页面。"""
    return Template(template_name="settings.html")


@get("/static/thumbnails/{filename:str}")
async def serve_thumbnail(filename: str) -> File:
    """
    服务缩略图文件。

    缩略图存储在 LIBRARY_ROOT/.thumbnails/ 目录下，
    由于 LIBRARY_ROOT 是动态配置的路径，需要通过专门的路由来服务。
    """
    settings = get_settings()
    thumbnails_dir = (settings.LIBRARY_ROOT / ".thumbnails").resolve()
    thumbnail_path = (thumbnails_dir / filename).resolve()

    if not thumbnail_path.is_relative_to(thumbnails_dir):
        raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail="Thumbnail not found")

    if not thumbnail_path.exists():
        raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail="Thumbnail not found")

    return File(
        path=thumbnail_path,
        media_type="image/jpeg",
        headers={"Cache-Control": "no-cache, must-revalidate"},
    )


@get("/previews/{filename:str}")
async def serve_preview(filename: str) -> File:
    """
    服务预览文件。

    预览文件存储在 PREVIEWS_ROOT 目录下，
    由于 PREVIEWS_ROOT 是动态配置的路径，需要通过专门的路由来服务。
    """
    import mimetypes

    settings = get_settings()
    previews_dir = settings.PREVIEWS_ROOT.resolve()
    preview_path = (previews_dir / filename).resolve()

    if not preview_path.exists() or not preview_path.is_relative_to(previews_dir):
        raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail="Preview not found")

    media_type = mimetypes.guess_type(str(preview_path))[0] or "application/octet-stream"
    return File(path=preview_path, content_disposition_type="inline", media_type=media_type)


_request_id: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")


class RequestIdFilter(logging.Filter):
    """将当前请求 ID 注入日志记录。"""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = _request_id.get()
        return True


access_logger = logging.getLogger("folark.access")


class AccessLogMiddleware(AbstractMiddleware):
    """记录 HTTP 请求的方法、路径、状态码和耗时。"""

    scopes = {"http"}
    exclude = ["/static"]

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        request_id = uuid_mod.uuid4().hex[:8]
        _request_id.set(request_id)
        start = time.monotonic()
        status_code = 500  # 默认值，异常时使用

        original_send = send

        async def send_wrapper(message: dict) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            await original_send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            duration_ms = (time.monotonic() - start) * 1000
            request_method = scope.get("method", "UNKNOWN")
            request_path = scope.get("path", "")
            query_string = scope.get("query_string", b"").decode("utf-8", errors="replace")
            full_path = f"{request_path}?{query_string}" if query_string else request_path
            access_logger.info(
                "[%s] %s %s %d %.1fms",
                request_id,
                request_method,
                full_path,
                status_code,
                duration_ms,
            )


def setup_logging(settings):
    """配置日志：同时输出到终端和文件。"""
    log_level = getattr(logging, settings.LOG_LEVEL.upper())
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] [%(request_id)s] %(name)s: %(message)s")

    # 注册 Request ID 过滤器
    request_id_filter = RequestIdFilter()

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    root_logger.addFilter(request_id_filter)

    # 检查是否已经添加过 RotatingFileHandler（避免重复添加）
    has_file_handler = any(isinstance(h, RotatingFileHandler) for h in root_logger.handlers)
    if has_file_handler:
        return

    # 统一格式：为已有的 handlers（如 uvicorn 添加的）也设置格式和过滤器
    for h in root_logger.handlers:
        h.setFormatter(formatter)
        h.setLevel(log_level)
        h.addFilter(request_id_filter)

    # 如果没有终端 handler，添加一个
    has_console = any(
        isinstance(h, logging.StreamHandler) and not isinstance(h, RotatingFileHandler) for h in root_logger.handlers
    )
    if not has_console:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(log_level)
        console_handler.setFormatter(formatter)
        console_handler.addFilter(request_id_filter)
        root_logger.addHandler(console_handler)

    # 文件输出（将 LOG_DIR 相对路径解析为相对于项目根目录的绝对路径）
    log_dir = settings.LOG_DIR
    if not log_dir.is_absolute():
        log_dir = PROJECT_ROOT / log_dir
    log_dir.mkdir(parents=True, exist_ok=True)

    # 主日志文件 — 记录所有级别
    file_handler = RotatingFileHandler(
        log_dir / "folark.log",
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(log_level)
    file_handler.setFormatter(formatter)
    file_handler.addFilter(request_id_filter)
    root_logger.addHandler(file_handler)

    # Access 日志文件 — 仅记录 folark.access 的请求日志
    access_handler = RotatingFileHandler(
        log_dir / "folark.access.log",
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    access_formatter = logging.Formatter("%(asctime)s %(message)s")
    access_handler.setLevel(logging.INFO)
    access_handler.setFormatter(access_formatter)
    access_log = logging.getLogger("folark.access")
    access_log.addHandler(access_handler)
    access_log.propagate = False  # 不传播到根 logger，避免重复输出

    # Error 日志文件 — 仅记录 WARNING 及以上级别
    error_handler = RotatingFileHandler(
        log_dir / "folark.error.log",
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    error_handler.setLevel(logging.WARNING)
    error_handler.setFormatter(formatter)
    error_handler.addFilter(request_id_filter)
    root_logger.addHandler(error_handler)

    # aiosqlite DEBUG 日志过于冗余，单独设为 INFO
    logging.getLogger("aiosqlite").setLevel(logging.INFO)


async def on_startup() -> None:
    """应用启动钩子。"""
    settings = get_settings()

    # 配置日志
    setup_logging(settings)

    # 确保 DATA_ROOT 存在
    settings.DATA_ROOT.mkdir(parents=True, exist_ok=True)

    # 确保 LIBRARY_ROOT 存在
    settings.LIBRARY_ROOT.mkdir(parents=True, exist_ok=True)

    # 确保缩略图目录存在
    thumbnails_dir = settings.LIBRARY_ROOT / ".thumbnails"
    thumbnails_dir.mkdir(parents=True, exist_ok=True)

    # 清空 .previews 目录（临时预览文件，每次启动重建）
    if settings.PREVIEWS_ROOT.exists():
        for f in settings.PREVIEWS_ROOT.iterdir():
            if f.is_file():
                f.unlink(missing_ok=True)
    settings.PREVIEWS_ROOT.mkdir(parents=True, exist_ok=True)

    # 初始化数据库
    await init_db(settings.DB_PATH)

    # 从 DB 加载用户自定义配置（热更新机制）
    await load_settings_from_db(get_db())
    settings = get_settings()  # 重新获取合并后的配置

    # 初始化插件管理器
    manager = PluginManager(settings)
    manager.load_builtin()
    manager.load_entry_points()
    await manager.sync_db(get_db())
    set_plugin_manager(manager)
    logger.info("插件管理器已初始化: 共加载 %d 个插件", len(manager.plugins))

    # 记录每种扩展名支持的下载和预览格式
    for ext in sorted(settings.ALLOWED_EXTENSIONS):
        preview_formats = manager.get_preview_formats(ext.lstrip("."))
        download_formats = manager.get_download_formats(ext.lstrip("."))
        logger.info("扩展名 %s: 预览格式=%s, 下载格式=%s", ext, preview_formats, download_formats)

    # 标记中断的批量任务
    from app.services.batch_jobs import mark_interrupted_jobs

    await mark_interrupted_jobs()

    logger.info("folark 已启动，LIBRARY_ROOT=%s", settings.LIBRARY_ROOT)


async def on_shutdown() -> None:
    await close_db()
    logger.info("folark 已关闭")


# 模板配置
template_config = TemplateConfig(
    directory=BASE_DIR / "templates",
    engine=JinjaTemplateEngine,
)

# 静态文件路由（项目根目录下的 static 目录）
static_files_router = create_static_files_router(
    path="/static",
    directories=[PROJECT_ROOT / "static"],
)

# 创建 Litestar 应用实例
settings = get_settings()
app = Litestar(
    route_handlers=[
        login_page,
        login_action,
        logout_action,
        index,
        import_page,
        settings_page,
        serve_thumbnail,
        serve_preview,
        documents_router,
        search_router,
        tags_router,
        plugins_router,
        settings_router,
        BatchJobController,
        static_files_router,
    ],
    template_config=template_config,
    middleware=[AuthMiddleware, AccessLogMiddleware],
    on_startup=[on_startup],
    on_shutdown=[on_shutdown],
    request_max_body_size=settings.MAX_UPLOAD_SIZE,
)


if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run("app.main:app", host="0.0.0.0", port=settings.PORT, reload=True)
