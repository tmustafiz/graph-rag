import os
from pathlib import Path

from sentence_transformers import CrossEncoder

DEFAULT_MODEL_NAME = "cross-encoder/ms-marco-MiniLM-L-6-v2"

# Truthy value here turns reranking on. Off by default: the base install and the
# runtime image ship without this model, and hybrid search works without it.
_ENABLE_ENV_VAR = "GRAG_RERANK"

# Explicit override: a local directory or a Hub repo id. Setting this to a Hub
# id (e.g. DEFAULT_MODEL_NAME) is how you opt in to an online download.
_MODEL_ENV_VAR = "GRAG_RERANK_MODEL"

# Container image: mount the model here (the Dockerfile does not bake it in).
_IMAGE_MODEL_DIR = Path("/opt/models/ms-marco-MiniLM-L-6-v2")

# Dev checkout: `make fetch-reranker` writes the model to
# models/ms-marco-MiniLM-L-6-v2/ at the project root (three parents up).
_REPO_MODEL_DIR = Path(__file__).resolve().parents[3] / "models" / "ms-marco-MiniLM-L-6-v2"

_TRUTHY = {"1", "true", "yes", "on"}


class CrossEncoderReranker:
    """Cross-encoder re-scoring of an already-fused candidate set.

    A bi-encoder (the `Embedder`) ranks by comparing independently computed
    vectors; a cross-encoder reads the query and a candidate document together
    and scores their relevance directly, which is more accurate but too slow to
    run over the whole corpus. So it runs only over the handful of candidates
    hybrid search already shortlisted.

    Resolves the model to a *local* copy: the `GRAG_RERANK_MODEL` env var (a
    directory, or a Hub repo id if you want an online download), a copy mounted
    into the container image at `/opt/models/ms-marco-MiniLM-L-6-v2`, or the
    `models/ms-marco-MiniLM-L-6-v2/` folder in a dev checkout. With none of
    those present it raises at construction — which is startup — rather than
    silently deferring a Hub download to the first query.
    """

    def __init__(self, model_name: str | None = None) -> None:
        self._model = CrossEncoder(model_name or self._resolve_model())

    @staticmethod
    def _resolve_model() -> str:
        override = os.environ.get(_MODEL_ENV_VAR)
        if override:
            return override
        for candidate in (_IMAGE_MODEL_DIR, _REPO_MODEL_DIR):
            if candidate.is_dir():
                return str(candidate)
        raise RuntimeError(
            f"{_ENABLE_ENV_VAR} is set but no local reranker model was found "
            f"(looked in {_IMAGE_MODEL_DIR} and {_REPO_MODEL_DIR}). Run "
            f"`make fetch-reranker`, or set {_MODEL_ENV_VAR} to a local path — "
            f"or to a Hub id such as {DEFAULT_MODEL_NAME!r} to allow an online "
            f"download."
        )

    def rerank(self, query: str, documents: list[str]) -> list[float]:
        """Relevance score for each `(query, document)` pair, in input order."""
        if not documents:
            return []
        scores = self._model.predict([(query, document) for document in documents])
        return [float(score) for score in scores]


def build_reranker() -> CrossEncoderReranker | None:
    """A `CrossEncoderReranker` when `GRAG_RERANK` is set to a truthy value
    (`1`, `true`, `yes`, `on`), else `None`. Raises at startup (not at first
    query) if reranking is enabled but no local model is available.
    """
    if os.environ.get(_ENABLE_ENV_VAR, "").strip().lower() in _TRUTHY:
        return CrossEncoderReranker()
    return None
