import json
import logging

import httpx

from .query_rewriter import DEFAULT_MAX_QUERIES, QueryRewriter, normalize_variants

logger = logging.getLogger(__name__)

_DEFAULT_API_BASE = "https://api.openai.com"
_DEFAULT_TIMEOUT_SECONDS = 15.0

_SYSTEM_PROMPT = (
    "You rewrite a search query for a hybrid retrieval system indexing technical "
    "documentation, source code, and infrastructure-as-code policies. Return ONLY "
    "a JSON array of between 1 and {max_queries} short search-query strings. "
    "Expand acronyms and project jargon, split a multi-part question into one "
    "self-contained sub-query per ask, and optionally paraphrase toward the "
    "vocabulary such documentation would use. Do not answer the question, explain, "
    "or add any text outside the JSON array."
)


class LlmQueryRewriter(QueryRewriter):
    """Query rewriting via an OpenAI-compatible `POST /v1/chat/completions`.

    Works against OpenAI itself or any compatible endpoint — a local Ollama or
    LM Studio server, vLLM, a gateway — by pointing `api_base` at it. Opt-in on
    top of `GRAG_QUERY_REWRITE`: selected only once `GRAG_QUERY_REWRITE_MODEL`
    names a model (see `query_rewriter_factory`).

    Every failure path — connection error, non-2xx, a response body that isn't a
    JSON array of strings, an empty array — is caught and logged, and `rewrite`
    falls back to `[query]`. It never raises and never fails a search.
    """

    def __init__(
        self,
        model: str,
        api_key: str,
        api_base: str | None = None,
        max_queries: int = DEFAULT_MAX_QUERIES,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._model = model
        self._api_key = api_key
        self._api_base = (api_base or _DEFAULT_API_BASE).rstrip("/")
        self._max_queries = max_queries
        self._timeout_seconds = timeout_seconds

    def rewrite(self, query: str) -> list[str]:
        try:
            variants = self._request_variants(query)
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            logger.warning("query rewriting skipped for %r: %s", query, exc)
            return [query]
        return normalize_variants(query, variants, self._max_queries)

    def _request_variants(self, query: str) -> list[str]:
        payload = {
            "model": self._model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT.format(max_queries=self._max_queries)},
                {"role": "user", "content": query},
            ],
        }
        with httpx.Client(timeout=self._timeout_seconds) as client:
            response = client.post(
                f"{self._api_base}/v1/chat/completions",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json=payload,
            )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        parsed = json.loads(_strip_code_fence(content))
        if not isinstance(parsed, list) or not all(isinstance(item, str) for item in parsed):
            raise ValueError(f"expected a JSON array of strings, got {content!r}")
        return parsed


def _strip_code_fence(content: str) -> str:
    """Tolerate a model that wraps the JSON array in a ```json ... ``` fence."""
    text = content.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0]
    return text.strip()
