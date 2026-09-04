import os
from abc import abstractmethod

import httpx

from .embedder import Embedder

_DEFAULT_TIMEOUT_SECONDS = 60.0


class RestEmbedder(Embedder):
    """Base for hosted embedding backends that speak plain JSON over HTTPS.

    Subclasses declare their provider identity and the default model/endpoint as
    class attributes, then implement `_build_request` (turn a batch of texts into
    an HTTP request) and `_extract` (pull the vectors back out of the response).
    This class owns the transport: one `httpx` call per batch, an explicit status
    check, and a length assertion so a truncated response fails loudly here rather
    than as a dimension error deep in Neo4j.

    No provider SDKs — every backend is a handful of lines against a documented
    REST endpoint, so the base install stays free of optional heavy dependencies.
    """

    provider_name: str
    default_model: str
    default_api_base: str

    def __init__(
        self,
        model: str | None = None,
        api_base: str | None = None,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._model = model or self.default_model
        self._api_base = (api_base or self.default_api_base).rstrip("/")
        self._timeout_seconds = timeout_seconds

    @property
    def model(self) -> str:
        return self._model

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        method, url, headers, payload = self._build_request(texts)
        try:
            with httpx.Client(timeout=self._timeout_seconds) as client:
                response = client.request(method, url, headers=headers, json=payload)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            body = exc.response.text[:500]
            raise RuntimeError(
                f"{self.provider_name} embeddings request failed "
                f"(HTTP {exc.response.status_code}): {body}"
            ) from exc
        except httpx.HTTPError as exc:
            raise RuntimeError(
                f"{self.provider_name} embeddings request could not be completed: {exc}"
            ) from exc

        vectors = self._extract(response.json(), len(texts))
        if len(vectors) != len(texts):
            raise RuntimeError(
                f"{self.provider_name} returned {len(vectors)} vectors for "
                f"{len(texts)} inputs — response was truncated or reordered."
            )
        return vectors

    @abstractmethod
    def _build_request(
        self, texts: list[str]
    ) -> tuple[str, str, dict[str, str], dict[str, object]]:
        """Return `(method, url, headers, json_body)` for one batch of texts."""

    @abstractmethod
    def _extract(self, payload: dict[str, object], count: int) -> list[list[float]]:
        """Pull `count` embedding vectors out of the decoded JSON response."""

    @staticmethod
    def _require_env(name: str) -> str:
        value = os.environ.get(name, "").strip()
        if not value:
            raise RuntimeError(f"{name} is not set — it is required for this embedding provider.")
        return value
