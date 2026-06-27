"""插件系统公共 API。"""

from app.plugins.core import (
    ON_DEMAND_HANDLER_TYPES,
    PIPELINE_HANDLER_TYPES,
    BasePlugin,
    ConvertResult,
    PluginContext,
    PreviewResult,
    TaskHandler,
    TaskHandlerInfo,
    TaskHandlerMode,
    TaskHandlerType,
    persist_task_result,
    task_handler,
)
from app.plugins.manager import PluginManager

__all__ = [
    "TaskHandlerType",
    "TaskHandlerMode",
    "TaskHandlerInfo",
    "TaskHandler",
    "BasePlugin",
    "task_handler",
    "PIPELINE_HANDLER_TYPES",
    "ON_DEMAND_HANDLER_TYPES",
    "PluginContext",
    "PreviewResult",
    "ConvertResult",
    "persist_task_result",
    "PluginManager",
]
