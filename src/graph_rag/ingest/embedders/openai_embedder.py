from .rest_embedder import RestEmbedder

_API_KEY_ENV_VAR = "OPENAI_API_KEY"


class OpenAiEmbedder(RestEmbedder):
    """OpenAI's `/v1/embeddings` endpoint, and any OpenAI-compatible gateway
    (vLLM, LM Studio, Together, a local proxy) reachable by pointing
    `GRAG_EMBEDDING_API_BASE` at its base URL.

    `text-embedding-3-small` is 1536-dimensional — set `EMBEDDING_DIMENSIONS`
    to match before applying the schema.
    """

    provider_name = "OpenAI"
    default_model = "text-embedding-3-small"
    default_api_base = "https://api.openai.com"

    def _build_request(
        self, texts: list[str]
    ) -> tuple[str, str, dict[str, str], dict[str, object]]:
        headers = {"Authorization": f"Bearer {self._require_env(_API_KEY_ENV_VAR)}"}
        payload: dict[str, object] = {"model": self._model, "input": texts}
        return "POST", f"{self._api_base}/v1/embeddings", headers, payload

    def _extract(self, payload: dict[str, object], count: int) -> list[list[float]]:
        rows = sorted(payload["data"], key=lambda row: row["index"])
        return [[float(value) for value in row["embedding"]] for row in rows]
