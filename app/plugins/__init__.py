"""插件系统公共 API。"""

from app.plugins.core import (
    BasePlugin,
    PluginContext,
    PreviewResult,
    ConvertResult,
    TaskHandler,
    TaskHandlerInfo,
    TaskHandlerMode,
    TaskHandlerType,
    task_handler,
    PIPELINE_HANDLER_TYPES,
    ON_DEMAND_HANDLER_TYPES,
    persist_task_result,
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
