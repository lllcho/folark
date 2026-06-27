"""插件管理器：注册、索引、加载与执行插件。

注册键为 (plugin_name, handler_name)，通过 plugin_name + handler_name 唯一定位任务处理器。
source_types 仅为描述性元数据，用于 find_handler 等便利查询方法的按需匹配。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.plugins.core import (
    BasePlugin,
    PluginContext,
    TaskHandler,
    TaskHandlerInfo,
    TaskHandlerType,
    TaskResult,
    expand_source_types,
)

logger = logging.getLogger(__name__)
_manager: PluginManager | None = None


def get_plugin_manager() -> PluginManager:
    """获取全局 PluginManager 单例。"""
    if _manager is None:
        raise RuntimeError("PluginManager not initialized")
    return _manager


def set_plugin_manager(manager: PluginManager) -> None:
    """设置全局 PluginManager 单例（由 main.py on_startup 调用）。"""
    global _manager
    _manager = manager


class PluginManager:
    """插件注册中心，以 (plugin_name, handler_name) 为核心索引。"""

    def __init__(self, settings: Any) -> None:
        self._settings = settings
        self.plugins: dict[str, BasePlugin] = {}
        self.handler_registry: dict[tuple[str, str], TaskHandler] = {}

    def register(self, plugin: BasePlugin) -> None:
        """注册一个插件：扫描 @task_handler 装饰器标记的方法并建立索引。"""
        if not getattr(plugin, "name", None):
            raise ValueError("Plugin missing required attribute: name")

        self.plugins[plugin.name] = plugin

        handler_count = 0
        for attr_name in dir(plugin):
            try:
                method = getattr(plugin, attr_name)
            except Exception:
                continue
            handler_info: TaskHandlerInfo | None = getattr(method, "_task_handler_info", None)
            if handler_info is None:
                continue

            key = (plugin.name, handler_info.handler_name)
            existing = self.handler_registry.get(key)
            if existing is not None and existing.plugin.name != plugin.name:
                logger.warning(
                    "处理器 '%s' (插件 '%s') 覆盖了 '%s'",
                    handler_info.handler_name,
                    plugin.name,
                    existing.plugin.name,
                )
            self.handler_registry[key] = TaskHandler(
                plugin=plugin,
                method=method,
                info=handler_info,
            )
            handler_count += 1

        logger.info(
            "插件已注册: %s v%s (%d 个处理器)",
            plugin.name,
            plugin.version,
            handler_count,
        )

    def execute(self, plugin_name: str, handler_name: str, ctx: PluginContext) -> TaskResult | None:
        """执行指定插件的任务处理器。"""
        handler = self.handler_registry.get((plugin_name, handler_name))
        if handler is None:
            logger.debug("未找到处理器: (%s, %s)", plugin_name, handler_name)
            return None

        if not handler.plugin.enabled:
            logger.warning("插件 '%s' 已禁用，跳过处理器 '%s'", plugin_name, handler_name)
            return None
        if not handler.enabled:
            logger.warning("处理器 '%s/%s' 已禁用", plugin_name, handler_name)
            return None

        try:
            return handler.method(ctx)
        except Exception:
            logger.exception(
                "插件 '%s' 在处理器 '%s' 执行时失败, 文件: %s",
                plugin_name,
                handler_name,
                ctx.file_name,
            )
            return None

    def get_handler_info(self, plugin_name: str, handler_name: str) -> TaskHandlerInfo | None:
        """获取指定 (plugin_name, handler_name) 的处理器元数据。"""
        handler = self.handler_registry.get((plugin_name, handler_name))
        return handler.info if handler else None

    def get_plugin(self, name: str) -> BasePlugin | None:
        """按名称获取插件实例。"""
        return self.plugins.get(name)

    # ── 便利查询方法（基于 handler_type + source_type 自动发现） ──
    def find_handler(self, handler_type: TaskHandlerType, source_type: str) -> TaskHandler | None:
        """按 (handler_type, source_type) 查找处理器，精确匹配优先于类别匹配。"""
        category_match: TaskHandler | None = None
        for handler in self.handler_registry.values():
            if handler.info.handler_type != handler_type:
                continue
            if not handler.plugin.enabled or not handler.enabled:
                continue
            if source_type in handler.info.source_types:
                return handler
            if category_match is None:
                expanded = expand_source_types(handler.info.source_types)
                if source_type in expanded:
                    category_match = handler
        return category_match

    def get_convert_targets(self, source_type: str) -> list[str]:
        """查询某 source_type 可转换的目标格式列表。"""
        targets: set[str] = set()
        for handler in self.handler_registry.values():
            if handler.info.handler_type != TaskHandlerType.CONVERT:
                continue
            if not handler.plugin.enabled or not handler.enabled:
                continue
            expanded = expand_source_types(handler.info.source_types)
            if source_type in expanded and handler.info.target_types:
                targets.update(handler.info.target_types)
        return list(targets)

    def get_preview_formats(self, source_type: str) -> list[str]:
        """返回该 source_type 可预览的格式列表。"""
        formats: list[str] = []
        if self.find_handler(TaskHandlerType.PREVIEW, source_type):
            formats.append(source_type)
        for target in self.get_convert_targets(source_type):
            if self.find_handler(TaskHandlerType.PREVIEW, target):
                formats.append(target)
        return list(dict.fromkeys(formats))

    def get_download_formats(self, source_type: str) -> list[str]:
        """返回该 source_type 可下载的格式列表（原格式 + 可转换格式）。"""
        formats = [source_type]
        formats.extend(self.get_convert_targets(source_type))
        return list(dict.fromkeys(formats))

    def load_builtin(self) -> None:
        """加载合并后的内置插件（builtin_plugin）。"""
        from app.plugins.builtin_plugin.plugin import BuiltinPlugin

        try:
            plugin_instance = BuiltinPlugin()
            plugin_instance.plugin_type = "builtin"
            self.register(plugin_instance)
            logger.info("内置插件已加载: %s", plugin_instance.name)
        except Exception:
            logger.exception("内置插件加载失败")

    def load_entry_points(self) -> None:
        """通过 entry_points(group='folark.plugins') 加载第三方插件。"""
        try:
            from importlib.metadata import entry_points

            eps = entry_points(group="folark.plugins")
            for ep in eps:
                try:
                    plugin_cls = ep.load()
                    plugin_instance = plugin_cls()
                    plugin_instance.plugin_type = "community"
                    self.register(plugin_instance)
                    logger.info("第三方插件已加载: %s", plugin_instance.name)
                except Exception:
                    logger.exception("第三方插件加载失败: %s", ep.name)
        except Exception:
            logger.debug("未找到 folark.plugins 的 entry_points")

    async def sync_db(self, db: Any) -> None:
        """启动时同步 plugins 表，新增或更新已注册插件的记录。

        对于已有记录，保留用户设置的任务 enabled 状态。
        同步完成后将 DB 中的 enabled 状态加载到内存对象属性。
        """
        for name, plugin in self.plugins.items():
            handlers_from_code = self._collect_handlers_json(name)

            # 读取数据库中已有记录（enabled, task_handlers, config 一次性查询）
            existing_handlers_map: dict[str, bool] = {}
            existing_plugin_enabled: bool | None = None
            existing_config: dict | None = None
            async with db.execute(
                "SELECT enabled, task_handlers, config FROM plugins WHERE name = ?", (name,)
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    existing_plugin_enabled = bool(row[0])
                    if row[1]:
                        try:
                            for t in json.loads(row[1]):
                                existing_handlers_map[t.get("handler_name", "")] = bool(t.get("enabled", 1))
                        except (json.JSONDecodeError, TypeError):
                            pass
                    if row[2]:
                        try:
                            existing_config = json.loads(row[2])
                        except (json.JSONDecodeError, TypeError):
                            pass

            # 合并 enabled 状态：已有的保留用户设置，新增的默认 enabled=1
            for t in handlers_from_code:
                hname = t["handler_name"]
                if hname in existing_handlers_map:
                    t["enabled"] = 1 if existing_handlers_map[hname] else 0

            tasks_json = json.dumps(handlers_from_code, ensure_ascii=False)

            # 同步 plugin.enabled：已有记录沿用 DB 值，新记录默认 True
            plugin.enabled = existing_plugin_enabled if existing_plugin_enabled is not None else True

            # 合并 DB 中的 config 覆盖值到插件实例
            if existing_config:
                plugin.update_config(existing_config)

            await db.execute(
                """INSERT INTO plugins (name, version, plugin_type, task_handlers)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(name) DO UPDATE SET
                       version = excluded.version,
                       plugin_type = excluded.plugin_type,
                       task_handlers = excluded.task_handlers,
                       updated_at = CURRENT_TIMESTAMP""",
                (name, plugin.version, plugin.plugin_type, tasks_json),
            )

        # 清理数据库中不再注册的旧插件记录
        registered_names = list(self.plugins.keys())
        if registered_names:
            placeholders = ",".join("?" * len(registered_names))
            await db.execute(
                f"DELETE FROM plugins WHERE name NOT IN ({placeholders})",
                registered_names,
            )
        await db.commit()

        # 从 DB 加载 handler 的 enabled 状态到内存对象
        await self._load_enabled_from_db(db)

    async def _load_enabled_from_db(self, db: Any) -> None:
        """从 DB 读取 handler 的 enabled 状态，同步到内存中的 TaskHandler 对象。"""
        # 批量查询所有已启用插件的 handlers 数据
        plugin_handlers: dict[str, dict[str, bool]] = {}
        async with db.execute("SELECT name, task_handlers FROM plugins WHERE enabled = 1") as cursor:
            async for row in cursor:
                if not row[1]:
                    continue
                try:
                    handlers_map = {t["handler_name"]: bool(t.get("enabled", 1)) for t in json.loads(row[1])}
                    plugin_handlers[row[0]] = handlers_map
                except (json.JSONDecodeError, TypeError):
                    pass

        for (plugin_name, handler_name), handler in self.handler_registry.items():
            handlers_map = plugin_handlers.get(plugin_name)
            if handlers_map and handler_name in handlers_map:
                handler.enabled = handlers_map[handler_name]
            else:
                handler.enabled = False

    def _collect_handlers_json(self, plugin_name: str) -> list[dict]:
        """从 handler_registry 中提取指定插件的 handlers JSON 列表。"""
        return [
            {
                "handler_name": handler.info.handler_name,
                "handler_type": handler.info.handler_type.value,
                "source_types": list(handler.info.source_types),
                "target_types": list(handler.info.target_types) if handler.info.target_types else None,
                "handler_mode": handler.info.handler_mode.value,
                "enabled": 1,
                "description": handler.info.description,
            }
            for (pname, _), handler in self.handler_registry.items()
            if pname == plugin_name
        ]
