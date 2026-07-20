"""插件发现机制测试.

测试命名空间包自动发现、内置插件注册、list/get 接口。
"""

from __future__ import annotations

from omnievolve.plugins.base import BasePlugin
from omnievolve.plugins.discovery import (
    clear_plugins,
    discover_plugins,
    get_plugin,
    list_plugins,
)


class _TestPlugin(BasePlugin):
    name = "test-plugin"
    version = "0.0.0"


class TestPluginDiscovery:
    """插件发现测试."""

    def setup_method(self) -> None:
        clear_plugins()

    def teardown_method(self) -> None:
        clear_plugins()

    def test_discover_builtin_plugins(self) -> None:
        """内置 quant 和 geo 插件应被自动发现."""
        plugins = discover_plugins()
        assert "quant" in plugins
        assert "geo" in plugins
        assert plugins["quant"].name == "quant"
        assert plugins["geo"].name == "geo"

    def test_get_plugin(self) -> None:
        discover_plugins()
        p = get_plugin("quant")
        assert p is not None
        assert "防过拟合" in p.DOMAIN_HINTS[0]

    def test_get_plugin_missing(self) -> None:
        assert get_plugin("nonexistent") is None

    def test_list_plugins(self) -> None:
        discover_plugins()
        names = list_plugins()
        assert "quant" in names
        assert "geo" in names

    def test_clear_plugins(self) -> None:
        discover_plugins()
        assert len(list_plugins()) >= 2
        clear_plugins()
        assert list_plugins() == []
