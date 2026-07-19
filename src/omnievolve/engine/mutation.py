"""Artifact materialize 与 diff apply.

S4-08: 实现候选 Artifact materialize 与 diff apply
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from omnievolve.storage.artifact_store import ArtifactStore

logger = logging.getLogger(__name__)


class ArtifactMaterializer:
    """将候选 Artifact 物化到工作目录."""

    def __init__(self, artifact_store: ArtifactStore) -> None:
        self._store = artifact_store

    def materialize(
        self,
        artifact_hash: str,
        target_dir: str | Path,
        *,
        filename: str = "main.py",
    ) -> Path:
        """将候选代码物化到目标目录.

        Args:
            artifact_hash: 候选代码 artifact 哈希
            target_dir: 目标目录
            filename: 输出文件名

        Returns:
            物化后的文件路径
        """
        target_dir = Path(target_dir)
        target_dir.mkdir(parents=True, exist_ok=True)

        code = self._store.load(artifact_hash)
        target_file = target_dir / filename
        target_file.write_bytes(code)

        logger.debug(f"Materialized artifact {artifact_hash[:8]} to {target_file}")
        return target_file

    def materialize_with_manifest(
        self,
        manifest_hash: str,
        target_dir: str | Path,
    ) -> list[Path]:
        """根据 Manifest 物化多个文件."""
        manifest = self._store.load_manifest(manifest_hash)
        target_dir = Path(target_dir)
        target_dir.mkdir(parents=True, exist_ok=True)

        files = []
        for entry in manifest.entries:
            data = self._store.load(entry.artifact_hash)
            file_path = target_dir / entry.path
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_bytes(data)
            files.append(file_path)

        return files

    def apply_diff(
        self,
        base_hash: str,
        diff_text: str,
        target_dir: str | Path,
        *,
        filename: str = "main.py",
    ) -> Path:
        """应用 diff 到基础代码.

        Args:
            base_hash: 基础代码 artifact 哈希
            diff_text: diff 文本
            target_dir: 目标目录

        Returns:
            应用 diff 后的文件路径
        """
        target_dir = Path(target_dir)
        target_dir.mkdir(parents=True, exist_ok=True)

        # 物化基础代码
        base_file = self.materialize(base_hash, target_dir, filename=filename)

        # 尝试应用 diff
        try:
            import subprocess

            result = subprocess.run(
                ["patch", "-p0", str(base_file)],
                input=diff_text,
                capture_output=True,
                text=True,
                cwd=str(target_dir),
            )
            if result.returncode != 0:
                # patch 失败，使用简单替换
                logger.warning(f"patch failed: {result.stderr}, using fallback")
                # 如果 diff 是完整代码，直接使用
                if not diff_text.startswith("---"):
                    base_file.write_text(diff_text)
        except FileNotFoundError:
            # patch 命令不可用
            logger.warning("patch command not available, using diff as full code")
            if not diff_text.startswith("---"):
                base_file.write_text(diff_text)

        return base_file


class MutationRegistry:
    """变异算子注册表.

    S4-10: 实现基础 Mutation Registry 占位
    S7-13: 实现 Mutation Operator Registry
    """

    def __init__(self) -> None:
        self._operators: dict[str, Any] = {}

    def register(self, name: str, operator: Any) -> None:
        """注册变异算子."""
        self._operators[name] = operator
        logger.info(f"Registered mutation operator: {name}")

    def get(self, name: str) -> Any | None:
        """获取算子."""
        return self._operators.get(name)

    def list_operators(self) -> list[str]:
        """列出所有算子."""
        return list(self._operators.keys())

    def select(self, mutation_mix: dict[str, float]) -> str:
        """根据变异混合概率选择算子.

        Args:
            mutation_mix: {"point": 0.5, "crossover": 0.3, "rewrite": 0.2}

        Returns:
            选中的算子名称
        """
        import random

        operators = list(mutation_mix.keys())
        weights = list(mutation_mix.values())
        return random.choices(operators, weights=weights, k=1)[0]


# 全局注册表
_global_registry = MutationRegistry()


def get_global_registry() -> MutationRegistry:
    """获取全局变异算子注册表."""
    return _global_registry
