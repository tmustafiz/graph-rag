import pytest

from graph_rag.ingest.embedders import (
    OpenAiEmbedder,
    SentenceTransformerEmbedder,
    build_embedder,
)
from graph_rag.ingest.embedders import embedder_factory as factory


@pytest.fixture(autouse=True)
def _clear_embedding_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "GRAG_EMBEDDING_PROVIDER",
        "GRAG_EMBEDDING_MODEL",
        "GRAG_EMBEDDING_API_BASE",
    ):
        monkeypatch.delenv(name, raising=False)


def test_defaults_to_the_local_sentence_transformer(monkeypatch: pytest.MonkeyPatch) -> None:
    built: list[object] = []
    monkeypatch.setattr(
        factory, "SentenceTransformerEmbedder", lambda: built.append("local") or "local-embedder"
    )

    assert build_embedder() == "local-embedder"
    assert built == ["local"]


@pytest.mark.parametrize("provider", ["local", "sentence-transformers", "LOCAL", ""])
def test_explicit_local_aliases_select_the_local_model(
    monkeypatch: pytest.MonkeyPatch, provider: str
) -> None:
    monkeypatch.setenv("GRAG_EMBEDDING_PROVIDER", provider)
    monkeypatch.setattr(factory, "SentenceTransformerEmbedder", lambda: "local-embedder")

    assert build_embedder() == "local-embedder"


def test_unknown_provider_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GRAG_EMBEDDING_PROVIDER", "not-a-provider")

    with pytest.raises(RuntimeError, match="not a known embedding provider"):
        build_embedder()


def test_hosted_provider_is_wired_with_model_and_base_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GRAG_EMBEDDING_PROVIDER", "openai")
    monkeypatch.setenv("GRAG_EMBEDDING_MODEL", "text-embedding-3-large")
    monkeypatch.setenv("GRAG_EMBEDDING_API_BASE", "http://gateway.internal")
    captured: dict[str, object] = {}

    class _StubEmbedder:
        def __init__(self, model: str | None = None, api_base: str | None = None) -> None:
            captured["model"] = model
            captured["api_base"] = api_base

        def embed(self, texts: list[str]) -> list[list[float]]:
            return [[0.0] * 384 for _ in texts]

    monkeypatch.setitem(factory._HOSTED_BACKENDS, "openai", _StubEmbedder)

    embedder = build_embedder()

    assert isinstance(embedder, _StubEmbedder)
    assert captured == {"model": "text-embedding-3-large", "api_base": "http://gateway.internal"}


def test_dimension_mismatch_fails_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GRAG_EMBEDDING_PROVIDER", "openai")

    class _WrongWidthEmbedder:
        def __init__(self, model: str | None = None, api_base: str | None = None) -> None:
            pass

        def embed(self, texts: list[str]) -> list[list[float]]:
            return [[0.0] * 1536 for _ in texts]  # index is 384-wide

    monkeypatch.setitem(factory._HOSTED_BACKENDS, "openai", _WrongWidthEmbedder)

    with pytest.raises(
        RuntimeError, match=r"returns 1536-dimensional vectors but EMBEDDING_DIMENSIONS is 384"
    ):
        build_embedder()


def test_hosted_backend_registry_covers_the_documented_providers() -> None:
    assert set(factory._HOSTED_BACKENDS) == {"openai", "ollama", "voyage", "cohere", "gemini"}
    assert factory._HOSTED_BACKENDS["openai"] is OpenAiEmbedder


def test_local_alias_set_does_not_accidentally_include_a_hosted_name() -> None:
    assert factory._LOCAL_PROVIDER_NAMES.isdisjoint(factory._HOSTED_BACKENDS)
    assert SentenceTransformerEmbedder is factory.SentenceTransformerEmbedder
