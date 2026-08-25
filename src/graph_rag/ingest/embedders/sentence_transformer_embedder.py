from sentence_transformers import SentenceTransformer

from .embedder import Embedder

DEFAULT_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"


class SentenceTransformerEmbedder(Embedder):
    """Local, offline embedding model — no API key required."""

    def __init__(self, model_name: str = DEFAULT_MODEL_NAME) -> None:
        self._model = SentenceTransformer(model_name)

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors = self._model.encode(texts, normalize_embeddings=True)
        return vectors.tolist()
