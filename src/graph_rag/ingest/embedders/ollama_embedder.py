from .rest_embedder import RestEmbedder


class OllamaEmbedder(RestEmbedder):
    """A local Ollama server's `/api/embed` batch endpoint — no API key.

    Point `GRAG_EMBEDDING_API_BASE` at the host if Ollama is not on
    `localhost:11434`. Dimension depends on the model (`nomic-embed-text` is
    768) — set `EMBEDDING_DIMENSIONS` to match.
    """

    provider_name = "Ollama"
    default_model = "nomic-embed-text"
    default_api_base = "http://localhost:11434"

    def _build_request(
        self, texts: list[str]
    ) -> tuple[str, str, dict[str, str], dict[str, object]]:
        payload: dict[str, object] = {"model": self._model, "input": texts}
        return "POST", f"{self._api_base}/api/embed", {}, payload

    def _extract(self, payload: dict[str, object], count: int) -> list[list[float]]:
        return [[float(value) for value in vector] for vector in payload["embeddings"]]
