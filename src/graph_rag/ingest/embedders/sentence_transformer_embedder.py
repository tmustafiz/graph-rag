import os
from pathlib import Path

from sentence_transformers import SentenceTransformer

from .embedder import Embedder

DEFAULT_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"

# Explicit override: a local directory or a Hub repo id. Also the seam the
# hosted-embedder work will hang off.
_MODEL_ENV_VAR = "GRAG_EMBEDDING_MODEL"

# Dev checkout: `make fetch-model` writes the model to models/all-MiniLM-L6-v2/
# at the project root (four parents up from this file).
_REPO_MODEL_DIR = Path(__file__).resolve().parents[4] / "models" / "all-MiniLM-L6-v2"

# Container image: the Dockerfile bakes the model in here, so the runtime never
# calls huggingface.co.
_IMAGE_MODEL_DIR = Path("/opt/models/all-MiniLM-L6-v2")


class SentenceTransformerEmbedder(Embedder):
    """Local, offline embedding model — no API key required.

    Resolves the model in this order: the `GRAG_EMBEDDING_MODEL` env var
    (a directory or a Hub repo id), the copy baked into the container image,
    the `models/all-MiniLM-L6-v2/` folder in a dev checkout, and finally the
    Hugging Face Hub repo id (the only branch that needs network).
    """

    def __init__(self, model_name: str | None = None) -> None:
        self._model = SentenceTransformer(model_name or self._resolve_model())

    @staticmethod
    def _resolve_model() -> str:
        override = os.environ.get(_MODEL_ENV_VAR)
        if override:
            return override
        for candidate in (_IMAGE_MODEL_DIR, _REPO_MODEL_DIR):
            if candidate.is_dir():
                return str(candidate)
        return DEFAULT_MODEL_NAME

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors = self._model.encode(texts, normalize_embeddings=True)
        return vectors.tolist()
