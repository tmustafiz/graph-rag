from abc import ABC, abstractmethod


class Embedder(ABC):
    """Turns text into embedding vectors. Pluggable so the local default
    (sentence-transformers) can later be swapped for a hosted provider.
    """

    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]: ...
