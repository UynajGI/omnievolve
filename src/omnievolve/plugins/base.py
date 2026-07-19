"""领域插件协议.

S5-06: 领域插件接口
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from omnievolve.eval.task_evaluator import CandidateArtifact, EvalOutput


@runtime_checkable
class Plugin(Protocol):
    """领域插件 Protocol."""

    name: str
    version: str

    def get_domain_hints(self, task_description: str) -> list[str]:
        """获取领域提示."""
        ...

    def get_rag_corpus(self) -> list[dict] | None:
        """获取 RAG 语料库."""
        ...

    def enrich_evaluation(
        self,
        candidate: CandidateArtifact,
        output: EvalOutput,
    ) -> dict[str, Any]:
        """补充评估指标.

        注意：只能补充领域指标或发出约束告警，
        不能静默改写任务主分数。
        """
        ...


class BasePlugin:
    """插件基类."""

    name: str = "base"
    version: str = "0.1.0"

    def get_domain_hints(self, task_description: str) -> list[str]:
        """获取领域提示."""
        return []

    def get_rag_corpus(self) -> list[dict] | None:
        """获取 RAG 语料库."""
        return None

    def enrich_evaluation(
        self,
        candidate: CandidateArtifact,
        output: EvalOutput,
    ) -> dict[str, Any]:
        """补充评估指标."""
        return {}


class PluginRegistry:
    """插件注册表."""

    def __init__(self) -> None:
        self._plugins: dict[str, Plugin] = {}

    def register(self, plugin: Plugin) -> None:
        """注册插件."""
        self._plugins[plugin.name] = plugin

    def get(self, name: str) -> Plugin | None:
        """获取插件."""
        return self._plugins.get(name)

    def list_plugins(self) -> list[str]:
        """列出所有插件."""
        return list(self._plugins.keys())

    def get_all_domain_hints(self, task_description: str) -> list[str]:
        """收集所有插件的领域提示."""
        hints = []
        for plugin in self._plugins.values():
            hints.extend(plugin.get_domain_hints(task_description))
        return hints

    def enrich_all_evaluations(
        self,
        candidate: CandidateArtifact,
        output: EvalOutput,
    ) -> dict[str, Any]:
        """收集所有插件的评估增强."""
        enriched = {}
        for name, plugin in self._plugins.items():
            result = plugin.enrich_evaluation(candidate, output)
            if result:
                enriched[name] = result
        return enriched
