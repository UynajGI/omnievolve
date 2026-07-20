"""OmniEvolve 领域插件（热插拔）.

支持动态插件发现: 第三方安装为 `omnievolve_ext.plugins.*` 命名空间包后自动注册。
"""

from omnievolve.plugins.base import BasePlugin
from omnievolve.plugins.discovery import (
    clear_plugins,
    discover_plugins,
    get_plugin,
    list_plugins,
)

__all__ = [
    "BasePlugin",
    "discover_plugins",
    "get_plugin",
    "list_plugins",
    "clear_plugins",
]
