"""Embedding 工具与 Profile.

S6-01: 冻结 EmbeddingProfile 数据模型
S6-02: 实现 Embedder Protocol 与 fake embedder
S6-03: 实现 API/Local Embedder Adapter
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

logger = logging.getLogger(__name__)


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
            h = hashlib.sha256(text.encode()).hexdigest()
            # 哈希只有 32 个 byte-pair；高维度时循环复用
            byte_count = self._dimension * 2
            h_cycled = h * (byte_count // len(h) + 1)
            vector = [int(h_cycled[i : i + 2], 16) / 255.0 for i in range(0, byte_count, 2)]
            vectors.append(vector[: self._dimension])
        return vectors


class LiteLLMEmbedder:
    """LiteLLM Embedder Adapter — API 嵌入模型."""

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
            logger.warning("litellm not available, falling back to FakeEmbedder")
            return FakeEmbedder(self._dimension).embed(texts)
        except Exception:
            logger.exception("LiteLLM embedding failed, falling back to FakeEmbedder")
            return FakeEmbedder(self._dimension).embed(texts)


class SentenceTransformerEmbedder:
    """本地 Embedder — 使用 sentence-transformers 模型.

    S6-04: 实现本地 Embedder Adapter

    支持所有 sentence-transformers 兼容模型：
    - bge-m3, all-MiniLM-L6-v2, all-mpnet-base-v2, etc.
    """

    def __init__(
        self,
        model: str = "all-MiniLM-L6-v2",
        *,
        device: str = "cpu",
        normalize: bool = True,
    ) -> None:
        self._model_name = model
        self._device = device
        self._normalize = normalize
        self._model = None  # 延迟加载

    @property
    def dimension(self) -> int:
        self._ensure_loaded()
        assert self._model is not None  # narrowed after _ensure_loaded
        return self._model.get_embedding_dimension()

    def embed(self, texts: list[str]) -> list[list[float]]:
        """使用本地模型嵌入."""
        self._ensure_loaded()
        assert self._model is not None  # narrowed after _ensure_loaded
        embeddings = self._model.encode(
            texts,
            normalize_embeddings=self._normalize,
            show_progress_bar=False,
        )
        return embeddings.tolist()

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return

        errors: list[str] = []

        # 1. HuggingFace 官方
        try:
            self._model = self._load_from_huggingface()
            assert self._model is not None
            logger.info(
                "Loaded local embedding model from HuggingFace: %s (dim=%d, device=%s)",
                self._model_name,
                self._model.get_embedding_dimension(),
                self._device,
            )
            return
        except Exception as e:
            errors.append(f"HuggingFace: {e}")

        # 2. HF 镜像（hf-mirror.com）
        try:
            self._model = self._load_from_hf_mirror()
            assert self._model is not None
            logger.info(
                "Loaded local embedding model from HF mirror: %s (dim=%d, device=%s)",
                self._model_name,
                self._model.get_embedding_dimension(),
                self._device,
            )
            return
        except Exception as e:
            errors.append(f"HF mirror: {e}")

        # 3. ModelScope（魔塔）
        try:
            self._model = self._load_from_modelscope()
            assert self._model is not None
            logger.info(
                "Loaded local embedding model from ModelScope: %s (dim=%d, device=%s)",
                self._model_name,
                self._model.get_embedding_dimension(),
                self._device,
            )
            return
        except Exception as e:
            errors.append(f"ModelScope: {e}")

        raise RuntimeError(
            f"Failed to load embedding model '{self._model_name}' from any source:\n"
            + "\n".join(f"  - {e}" for e in errors)
        ) from None

    def _load_from_huggingface(self):
        """从 HuggingFace 官方加载模型."""
        import os

        from sentence_transformers import SentenceTransformer

        os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "15")
        return SentenceTransformer(self._model_name, device=self._device)

    def _load_from_hf_mirror(self):
        """从 HF 镜像（hf-mirror.com）加载模型."""
        import os

        from sentence_transformers import SentenceTransformer

        os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
        try:
            return SentenceTransformer(self._model_name, device=self._device)
        finally:
            os.environ.pop("HF_ENDPOINT", None)

    def _load_from_modelscope(self):
        """从 ModelScope（魔塔）加载模型.

        使用 modelscope SDK 下载模型到本地缓存，再用 SentenceTransformer 加载。
        """
        from sentence_transformers import SentenceTransformer

        try:
            from modelscope import snapshot_download

            model_dir = snapshot_download(self._model_name)
            return SentenceTransformer(model_dir, device=self._device)
        except ImportError:
            raise ImportError(
                "modelscope is required for ModelScope downloads. "
                "Install with: pip install modelscope"
            ) from None


def create_embedder(
    provider: str,
    model: str,
    *,
    dimension: int = 1024,
    api_key: str | None = None,
    device: str = "cpu",
) -> Embedder:
    """根据 provider 创建 Embedder.

    Args:
        provider: "local" / "openai" / "voyage" / "litellm"
        model: 模型名
        dimension: 向量维度（API 模式用作 fallback）
        api_key: API key（API 模式）
        device: 设备（local 模式，"cpu" 或 "cuda"）

    Returns:
        Embedder 实例
    """
    if provider == "local":
        return SentenceTransformerEmbedder(model=model, device=device)

    # API 模式：统一走 LiteLLM
    return LiteLLMEmbedder(model=model, dimension=dimension, api_key=api_key)
