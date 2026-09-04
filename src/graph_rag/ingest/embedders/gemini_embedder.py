from .rest_embedder import RestEmbedder

_API_KEY_ENV_VAR = "GEMINI_API_KEY"


class GeminiEmbedder(RestEmbedder):
    """Google's Generative Language API `:batchEmbedContents` endpoint.

    `text-embedding-004` is 768-dimensional — set `EMBEDDING_DIMENSIONS` to
    match. The API key goes on the query string, as this API expects.
    """

    provider_name = "Gemini"
    default_model = "text-embedding-004"
    default_api_base = "https://generativelanguage.googleapis.com"

    def _build_request(
        self, texts: list[str]
    ) -> tuple[str, str, dict[str, str], dict[str, object]]:
        model_path = self._model if self._model.startswith("models/") else f"models/{self._model}"
        api_key = self._require_env(_API_KEY_ENV_VAR)
        url = f"{self._api_base}/v1beta/{model_path}:batchEmbedContents?key={api_key}"
        payload: dict[str, object] = {
            "requests": [
                {"model": model_path, "content": {"parts": [{"text": text}]}} for text in texts
            ]
        }
        return "POST", url, {}, payload

    def _extract(self, payload: dict[str, object], count: int) -> list[list[float]]:
        return [[float(value) for value in row["values"]] for row in payload["embeddings"]]
