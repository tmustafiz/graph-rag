from graph_rag.ingest.embedder import Embedder
from graph_rag.ingest.parsed_document import ParsedDocument


class Enricher:
    """Fills in `Chunk.embedding` for every chunk in a parsed document."""

    def __init__(self, embedder: Embedder) -> None:
        self._embedder = embedder

    def enrich(self, document: ParsedDocument) -> ParsedDocument:
        if not document.chunks:
            return document
        vectors = self._embedder.embed([chunk.text for chunk in document.chunks])
        enriched_chunks = [
            chunk.model_copy(update={"embedding": vector})
            for chunk, vector in zip(document.chunks, vectors, strict=True)
        ]
        return document.model_copy(update={"chunks": enriched_chunks})
