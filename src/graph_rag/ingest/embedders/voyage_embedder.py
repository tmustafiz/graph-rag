from .rest_embedder import RestEmbedder

_API_KEY_ENV_VAR = "VOYAGE_API_KEY"


class VoyageEmbedder(RestEmbedder):
    """Voyage AI's `/v1/embeddings` endpoint (OpenAI-shaped response).

    `voyage-3` is 1024-dimensional. Every text is sent with `input_type`
    `document`; see the `RestEmbedder` note on the lack of a query/document
    distinction in the `Embedder` interface.
    """

    provider_name = "Voyage"
    default_model = "voyage-3"
    default_api_base = "https://api.voyageai.com"

    def _build_request(
        self, texts: list[str]
    ) -> tuple[str, str, dict[str, str], dict[str, object]]:
        headers = {"Authorization": f"Bearer {self._require_env(_API_KEY_ENV_VAR)}"}
        payload: dict[str, object] = {
            "model": self._model,
            "input": texts,
            "input_type": "document",
        }
        return "POST", f"{self._api_base}/v1/embeddings", headers, payload

    def _extract(self, payload: dict[str, object], count: int) -> list[list[float]]:
        rows = sorted(payload["data"], key=lambda row: row["index"])
        return [[float(value) for value in row["embedding"]] for row in rows]
