"""Embedding 工具与 Profile.

S6-01: 冻结 EmbeddingProfile 数据模型
S6-02: 实现 Embedder Protocol 与 fake embedder
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class EmbeddingProfile:
    """Embedding Profile - 记录嵌入模型配置."""

    id: str
    purpose: str  # code / thought
    provider: str
    model: str
    revision: str | None = None
    dimension: int = 1024
    normalization: str | None = None
    input_type: str | None = None
    chunking_policy: str | None = None
    collection_path: str = ""


@runtime_checkable
class Embedder(Protocol):
    """Embedder Protocol."""

    def embed(self, texts: list[str]) -> list[list[float]]:
        """嵌入文本列表."""
        ...

    @property
    def dimension(self) -> int:
        """向量维度."""
        ...


class FakeEmbedder:
    """Fake Embedder for testing."""

    def __init__(self, dimension: int = 128) -> None:
        self._dimension = dimension

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed(self, texts: list[str]) -> list[list[float]]:
        """生成确定性伪向量."""
        import hashlib

        vectors = []
        for text in texts:
            # 使用文本哈希生成确定性向量
            h = hashlib.sha256(text.encode()).hexdigest()
            vector = [int(h[i : i + 2], 16) / 255.0 for i in range(0, self._dimension * 2, 2)]
            vectors.append(vector[: self._dimension])
        return vectors


class LiteLLMEmbedder:
    """LiteLLM Embedder Adapter."""

    def __init__(
        self,
        model: str = "text-embedding-3-small",
        dimension: int = 1536,
        api_key: str | None = None,
    ) -> None:
        self._model = model
        self._dimension = dimension
        self._api_key = api_key

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed(self, texts: list[str]) -> list[list[float]]:
        """调用 LiteLLM embedding API."""
        try:
            import litellm

            response = litellm.embedding(
                model=self._model,
                input=texts,
                api_key=self._api_key,
            )
            return [item["embedding"] for item in response.data]
        except ImportError:
            # 回退到 FakeEmbedder
            return FakeEmbedder(self._dimension).embed(texts)
