"""embedding.py 单元测试 — Embedder 实现 + create_embedder 工厂."""

from __future__ import annotations

import pytest

from omnievolve.utils.embedding import (
    Embedder,
    EmbeddingProfile,
    FakeEmbedder,
    LiteLLMEmbedder,
    SentenceTransformerEmbedder,
    create_embedder,
)

pytestmark = pytest.mark.unit


class TestEmbeddingProfile:
    def test_create_code_profile(self):
        p = EmbeddingProfile(
            id="code-v1",
            purpose="code",
            provider="local",
            model="all-MiniLM-L6-v2",
            dimension=384,
            collection_path=".omnievolve/vectors/code",
        )
        assert p.purpose == "code"
        assert p.dimension == 384

    def test_create_thought_profile(self):
        p = EmbeddingProfile(
            id="thought-v1",
            purpose="thought",
            provider="openai",
            model="text-embedding-3-small",
            dimension=1536,
        )
        assert p.purpose == "thought"
        assert p.provider == "openai"


class TestFakeEmbedder:
    def test_dimension(self):
        e = FakeEmbedder(dimension=256)
        assert e.dimension == 256

    def test_embed_returns_correct_shape(self):
        e = FakeEmbedder(dimension=128)
        result = e.embed(["hello", "world"])
        assert len(result) == 2
        assert len(result[0]) == 128

    def test_embed_is_deterministic(self):
        e = FakeEmbedder(dimension=64)
        r1 = e.embed(["test"])
        r2 = e.embed(["test"])
        assert r1 == r2

    def test_embed_different_texts_different_vectors(self):
        e = FakeEmbedder(dimension=64)
        r1 = e.embed(["hello"])
        r2 = e.embed(["world"])
        assert r1 != r2


class TestLiteLLMEmbedder:
    def test_init_defaults(self):
        e = LiteLLMEmbedder()
        assert e.dimension == 1536

    def test_custom_model_and_dimension(self):
        e = LiteLLMEmbedder(model="voyage-code-3", dimension=1024)
        assert e.dimension == 1024

    def test_embed_falls_back_to_fake_on_import_error(self):
        """没有 litellm 时回退到 FakeEmbedder."""
        e = LiteLLMEmbedder(dimension=64)
        result = e.embed(["hello"])
        assert len(result) == 1
        assert len(result[0]) == 64


class TestSentenceTransformerEmbedder:
    def test_init_does_not_load_immediately(self):
        """延迟加载：初始化时不加载模型."""
        e = SentenceTransformerEmbedder(model="all-MiniLM-L6-v2")
        assert e._model is None  # noqa: SLF001

    def test_missing_sentence_transformers_raises(self):
        """没有 sentence-transformers 时给出清晰错误."""
        e = SentenceTransformerEmbedder(model="nonexistent-model")

        import builtins

        orig_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if "sentence_transformers" in name:
                raise ImportError("No module named 'sentence_transformers'")
            return orig_import(name, *args, **kwargs)

        builtins.__import__ = mock_import
        try:
            e._model = None  # noqa: SLF001
            with pytest.raises(RuntimeError, match="Failed to load"):
                _ = e.dimension
        finally:
            builtins.__import__ = orig_import

    def test_dimension_cached_after_load(self):
        """加载后 dimension 被缓存."""
        e = SentenceTransformerEmbedder(model="all-MiniLM-L6-v2")

        class MockModel:
            def get_embedding_dimension(self):
                return 384

        e._model = MockModel()  # noqa: SLF001
        assert e.dimension == 384
        assert e.dimension == 384  # 缓存不变

    def test_fallback_to_modelscope_on_hf_failure(self):
        """HF 官方失败 → HF 镜像 → ModelScope 三级 fallback."""
        e = SentenceTransformerEmbedder(model="test-model")

        call_order = []

        def mock_hf_load(self):
            call_order.append("hf")
            raise OSError("Connection refused")

        def mock_hf_mirror_load(self):
            call_order.append("hf-mirror")
            raise OSError("mirror also unreachable")

        def mock_ms_load(self):
            call_order.append("modelscope")

            class MockModel:
                def get_embedding_dimension(self):
                    return 768

            return MockModel()

        e._load_from_huggingface = mock_hf_load.__get__(e)  # noqa: SLF001
        e._load_from_hf_mirror = mock_hf_mirror_load.__get__(e)  # noqa: SLF001
        e._load_from_modelscope = mock_ms_load.__get__(e)  # noqa: SLF001
        e._model = None  # noqa: SLF001

        e._ensure_loaded()  # noqa: SLF001
        assert call_order == ["hf", "hf-mirror", "modelscope"]
        assert e.dimension == 768

    def test_all_three_sources_fail(self):
        """三个源都失败时给出汇总错误."""
        e = SentenceTransformerEmbedder(model="bad-model")

        def fail(_self):
            raise OSError("network error")

        e._load_from_huggingface = fail.__get__(e)  # noqa: SLF001
        e._load_from_hf_mirror = fail.__get__(e)  # noqa: SLF001
        e._load_from_modelscope = fail.__get__(e)  # noqa: SLF001
        e._model = None  # noqa: SLF001

        with pytest.raises(RuntimeError, match="Failed to load"):
            e._ensure_loaded()  # noqa: SLF001


class TestCreateEmbedder:
    def test_create_local_embedder(self):
        e = create_embedder("local", "bge-m3")
        assert isinstance(e, SentenceTransformerEmbedder)

    def test_create_fake_embedder(self):
        e = create_embedder("fake", "deterministic-hash", dimension=64)
        assert isinstance(e, FakeEmbedder)
        assert e.dimension == 64

    def test_create_api_embedder(self):
        e = create_embedder("openai", "text-embedding-3-small", dimension=1536)
        assert isinstance(e, LiteLLMEmbedder)
        assert e.dimension == 1536

    def test_create_voyage_embedder(self):
        e = create_embedder("voyage", "voyage-code-3", dimension=1024, api_key="vk-xxx")
        assert isinstance(e, LiteLLMEmbedder)
        assert e.dimension == 1024

    def test_create_with_device(self):
        e = create_embedder("local", "all-MiniLM-L6-v2", device="cpu")
        assert isinstance(e, SentenceTransformerEmbedder)

    def test_unknown_provider_fails_closed(self):
        with pytest.raises(ValueError, match="Unsupported embedding provider"):
            create_embedder("unknown", "model")

    def test_embedder_satisfies_protocol(self):
        """所有 embedder 都满足 Embedder Protocol."""
        fake = FakeEmbedder()
        assert isinstance(fake, Embedder)
        # LiteLLMEmbedder falls back to fake on import error
        api = LiteLLMEmbedder(dimension=64)
        assert isinstance(api, Embedder)
