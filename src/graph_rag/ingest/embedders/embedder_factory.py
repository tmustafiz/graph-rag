import os

from graph_rag.settings import settings

from .cohere_embedder import CohereEmbedder
from .embedder import Embedder
from .gemini_embedder import GeminiEmbedder
from .ollama_embedder import OllamaEmbedder
from .openai_embedder import OpenAiEmbedder
from .rest_embedder import RestEmbedder
from .sentence_transformer_embedder import SentenceTransformerEmbedder
from .voyage_embedder import VoyageEmbedder

_PROVIDER_ENV_VAR = "GRAG_EMBEDDING_PROVIDER"
_MODEL_ENV_VAR = "GRAG_EMBEDDING_MODEL"
_API_BASE_ENV_VAR = "GRAG_EMBEDDING_API_BASE"

# Unset or any of these means "use the bundled local sentence-transformers model".
_LOCAL_PROVIDER_NAMES = {"", "local", "sentence-transformers"}

_HOSTED_BACKENDS: dict[str, type[RestEmbedder]] = {
    "openai": OpenAiEmbedder,
    "ollama": OllamaEmbedder,
    "voyage": VoyageEmbedder,
    "cohere": CohereEmbedder,
    "gemini": GeminiEmbedder,
}


def build_embedder() -> Embedder:
    """Return the embedder selected by `GRAG_EMBEDDING_PROVIDER`.

    Defaults to the offline `SentenceTransformerEmbedder` (no API key, no network).
    Any other value selects a hosted REST backend, configured by
    `GRAG_EMBEDDING_MODEL` (the provider's model id) and, optionally,
    `GRAG_EMBEDDING_API_BASE` (an endpoint override — an OpenAI-compatible
    gateway, or an Ollama host). A hosted backend is probed once here so a
    model/index dimension mismatch fails at startup, not mid-ingest.
    """
    provider = os.environ.get(_PROVIDER_ENV_VAR, "").strip().lower()
    if provider in _LOCAL_PROVIDER_NAMES:
        return SentenceTransformerEmbedder()

    backend_class = _HOSTED_BACKENDS.get(provider)
    if backend_class is None:
        supported = ", ".join(sorted(_HOSTED_BACKENDS))
        raise RuntimeError(
            f"{_PROVIDER_ENV_VAR}={provider!r} is not a known embedding provider "
            f"(expected 'local' or one of: {supported})."
        )

    embedder = backend_class(
        model=os.environ.get(_MODEL_ENV_VAR) or None,
        api_base=os.environ.get(_API_BASE_ENV_VAR) or None,
    )
    _assert_dimensions_match_index(embedder, provider)
    return embedder


def _assert_dimensions_match_index(embedder: Embedder, provider: str) -> None:
    actual = len(embedder.embed(["dimension probe"])[0])
    expected = settings.embedding_dimensions
    if actual != expected:
        raise RuntimeError(
            f"The {provider} embedding model returns {actual}-dimensional vectors "
            f"but EMBEDDING_DIMENSIONS is {expected}. Set EMBEDDING_DIMENSIONS="
            f"{actual} in your .env, re-run `grag-mcp apply-schema`, and re-ingest "
            f"so the Neo4j vector index matches."
        )
