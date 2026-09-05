import json
import logging
import os
from pathlib import Path

from .heuristic_query_rewriter import HeuristicQueryRewriter
from .llm_query_rewriter import LlmQueryRewriter
from .query_rewriter import DEFAULT_MAX_QUERIES, QueryRewriter

logger = logging.getLogger(__name__)

# Master switch. Unset/falsy keeps retrieval on its current unrewritten path.
_ENABLE_ENV_VAR = "GRAG_QUERY_REWRITE"

# Naming a model opts in to the LLM backend; without it the heuristic backend runs.
_MODEL_ENV_VAR = "GRAG_QUERY_REWRITE_MODEL"
_API_BASE_ENV_VAR = "GRAG_QUERY_REWRITE_API_BASE"
_API_KEY_ENV_VAR = "GRAG_QUERY_REWRITE_API_KEY"
_FALLBACK_API_KEY_ENV_VAR = "OPENAI_API_KEY"

# JSON object of `{"term": "expansion"}` merged over the heuristic backend's
# built-in acronym map.
_SYNONYMS_ENV_VAR = "GRAG_QUERY_REWRITE_SYNONYMS"

_MAX_QUERIES_ENV_VAR = "GRAG_QUERY_REWRITE_MAX_QUERIES"

_TRUTHY = {"1", "true", "yes", "on"}


def build_query_rewriter() -> QueryRewriter | None:
    """A `QueryRewriter` when `GRAG_QUERY_REWRITE` is truthy (`1`, `true`, `yes`,
    `on`), else `None`.

    With the switch on and no `GRAG_QUERY_REWRITE_MODEL`, the offline
    `HeuristicQueryRewriter` is used. Setting `GRAG_QUERY_REWRITE_MODEL` selects
    the `LlmQueryRewriter` instead and then requires an API key
    (`GRAG_QUERY_REWRITE_API_KEY`, or `OPENAI_API_KEY`) — missing, it raises at
    startup rather than failing on the first query.
    """
    if os.environ.get(_ENABLE_ENV_VAR, "").strip().lower() not in _TRUTHY:
        return None
    return select_query_rewriter()


def select_query_rewriter(max_queries: int | None = None) -> QueryRewriter:
    """Pick and construct the backend from the environment, without consulting
    the `GRAG_QUERY_REWRITE` switch — for callers that opt in explicitly, such
    as `grag-mcp eval-retrieval --rewrite`.
    """
    resolved_max = max_queries if max_queries is not None else _read_max_queries()
    model = os.environ.get(_MODEL_ENV_VAR, "").strip()
    if model:
        api_key = _resolve_api_key()
        return LlmQueryRewriter(
            model=model,
            api_key=api_key,
            api_base=os.environ.get(_API_BASE_ENV_VAR) or None,
            max_queries=resolved_max,
        )
    return HeuristicQueryRewriter(synonyms=_load_synonyms(), max_queries=resolved_max)


def _resolve_api_key() -> str:
    api_key = (
        os.environ.get(_API_KEY_ENV_VAR) or os.environ.get(_FALLBACK_API_KEY_ENV_VAR) or ""
    ).strip()
    if not api_key:
        raise RuntimeError(
            f"{_MODEL_ENV_VAR} is set but no API key was found — set "
            f"{_API_KEY_ENV_VAR} (or {_FALLBACK_API_KEY_ENV_VAR}), or unset "
            f"{_MODEL_ENV_VAR} to use the offline heuristic rewriter."
        )
    return api_key


def _read_max_queries() -> int:
    raw = os.environ.get(_MAX_QUERIES_ENV_VAR, "").strip()
    if not raw:
        return DEFAULT_MAX_QUERIES
    try:
        value = int(raw)
    except ValueError:
        logger.warning(
            "%s=%r is not an integer — using default %d",
            _MAX_QUERIES_ENV_VAR,
            raw,
            DEFAULT_MAX_QUERIES,
        )
        return DEFAULT_MAX_QUERIES
    return max(value, 1)


def _load_synonyms() -> dict[str, str] | None:
    path = os.environ.get(_SYNONYMS_ENV_VAR, "").strip()
    if not path:
        return None
    try:
        loaded = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning(
            "%s=%r could not be read as JSON (%s) — ignoring", _SYNONYMS_ENV_VAR, path, exc
        )
        return None
    if not isinstance(loaded, dict) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in loaded.items()
    ):
        logger.warning(
            "%s=%r is not a JSON object of string to string — ignoring", _SYNONYMS_ENV_VAR, path
        )
        return None
    return loaded
