from .rest_embedder import RestEmbedder

_API_KEY_ENV_VAR = "CO_API_KEY"


class CohereEmbedder(RestEmbedder):
    """Cohere's `/v2/embed` endpoint.

    `embed-english-v3.0` is 1024-dimensional. Cohere distinguishes query from
    document embeddings via `input_type`; the `Embedder` interface does not, so
    every text is sent as `search_document`. Retrieval queries are therefore
    embedded slightly off-optimally — acceptable until the interface grows a
    query/document flag.
    """

    provider_name = "Cohere"
    default_model = "embed-english-v3.0"
    default_api_base = "https://api.cohere.com"

    def _build_request(
        self, texts: list[str]
    ) -> tuple[str, str, dict[str, str], dict[str, object]]:
        headers = {"Authorization": f"Bearer {self._require_env(_API_KEY_ENV_VAR)}"}
        payload: dict[str, object] = {
            "model": self._model,
            "texts": texts,
            "input_type": "search_document",
            "embedding_types": ["float"],
        }
        return "POST", f"{self._api_base}/v2/embed", headers, payload

    def _extract(self, payload: dict[str, object], count: int) -> list[list[float]]:
        floats = payload["embeddings"]["float"]
        return [[float(value) for value in vector] for vector in floats]
