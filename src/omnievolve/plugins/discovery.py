"""动态插件发现机制.

参考 EvoX evox_ext.autoload_ext: 命名空间包自动发现 + 合并。
第三方插件安装为 `omnievolve_ext.*` 命名空间包后，
框架启动时自动发现并注册，无需修改 OmniEvolve 源码。
"""

from __future__ import annotations

import importlib
import inspect
import logging
import pkgutil
import types

from omnievolve.plugins.base import BasePlugin

logger = logging.getLogger(__name__)

_REGISTERED_PLUGINS: dict[str, BasePlugin] = {}


def discover_plugins() -> dict[str, BasePlugin]:
    """发现并加载所有 omnievolve_ext.* 命名空间包中的插件.

    扫描顺序:
        1. omnievolve_ext.plugins.* — 第三方插件
        2. omnievolve.plugins.* — 内置插件

    Returns:
        注册的插件字典 {name: plugin_instance}
    """
    _discover_from_namespace("omnievolve_ext.plugins")
    _discover_from_namespace("omnievolve.plugins")
    return dict(_REGISTERED_PLUGINS)


def _discover_from_namespace(namespace: str) -> None:
    """扫描命名空间包下的所有插件模块."""
    try:
        ns_pkg = importlib.import_module(namespace)
    except ImportError:
        logger.debug("Namespace %s not available, skipping", namespace)
        return

    if not hasattr(ns_pkg, "__path__"):
        logger.debug("%s is not a namespace package", namespace)
        return

    for finder, name, ispkg in pkgutil.iter_modules(ns_pkg.__path__, ns_pkg.__name__ + "."):
        try:
            module = importlib.import_module(name)
            if ispkg:
                # 子包：扫描 __init__.py 中导出的类
                _register_from_package(module)
            else:
                _register_plugins_from_module(module)
        except ImportError as e:
            logger.warning("Failed to import plugin module %s: %s", name, e)


def _register_from_package(module: types.ModuleType) -> None:
    """从子包的 __all__ 或顶层属性中注册插件."""
    # 先尝试直接扫描模块属性
    _register_plugins_from_module(module)


def _register_plugins_from_module(module: types.ModuleType) -> None:
    """从模块中注册所有 BasePlugin 子类."""
    for attr_name in dir(module):
        attr = getattr(module, attr_name)
        if inspect.isclass(attr) and issubclass(attr, BasePlugin) and attr is not BasePlugin:
            try:
                instance = attr()
                if instance.name not in _REGISTERED_PLUGINS:
                    _REGISTERED_PLUGINS[instance.name] = instance
                    logger.info("Registered plugin: %s (v%s)", instance.name, instance.version)
            except Exception as e:
                logger.warning("Failed to instantiate plugin %s: %s", attr.__name__, e)


def get_plugin(name: str) -> BasePlugin | None:
    """获取已注册的插件."""
    return _REGISTERED_PLUGINS.get(name)


def list_plugins() -> list[str]:
    """列出所有已注册的插件名称."""
    return list(_REGISTERED_PLUGINS.keys())


def clear_plugins() -> None:
    """清除所有已注册插件（主要用于测试）."""
    _REGISTERED_PLUGINS.clear()
