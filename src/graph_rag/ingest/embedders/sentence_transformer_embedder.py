from pathlib import Path

from sentence_transformers import SentenceTransformer

from .embedder import Embedder

DEFAULT_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"

_VENDORED_MODEL_DIR = Path(__file__).resolve().parents[4] / "models" / "all-MiniLM-L6-v2"


class SentenceTransformerEmbedder(Embedder):
    """Local, offline embedding model — no API key required.

    Loads the model from the vendored `models/all-MiniLM-L6-v2/` copy in
    this repo when present, so no network call to huggingface.co is ever
    needed; falls back to the Hugging Face Hub repo id otherwise.
    """

    def __init__(self, model_name: str | None = None) -> None:
        if model_name is None:
            model_name = (
                str(_VENDORED_MODEL_DIR) if _VENDORED_MODEL_DIR.is_dir() else DEFAULT_MODEL_NAME
            )
        self._model = SentenceTransformer(model_name)

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors = self._model.encode(texts, normalize_embeddings=True)
        return vectors.tolist()
