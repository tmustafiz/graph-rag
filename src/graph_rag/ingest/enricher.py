from .embedders import Embedder
from .models import ParsedDocument


class Enricher:
    """Fills in the `embedding` field for every chunk/code entity/policy rule in a document."""

    def __init__(self, embedder: Embedder) -> None:
        self._embedder = embedder

    def enrich(self, document: ParsedDocument) -> ParsedDocument:
        updates = {}
        if document.chunks:
            vectors = self._embedder.embed([chunk.text for chunk in document.chunks])
            updates["chunks"] = [
                chunk.model_copy(update={"embedding": vector})
                for chunk, vector in zip(document.chunks, vectors, strict=True)
            ]
        if document.code_entities:
            vectors = self._embedder.embed([entity.embed_text for entity in document.code_entities])
            updates["code_entities"] = [
                entity.model_copy(update={"embedding": vector})
                for entity, vector in zip(document.code_entities, vectors, strict=True)
            ]
        if document.policy_rules:
            vectors = self._embedder.embed([rule.embed_text for rule in document.policy_rules])
            updates["policy_rules"] = [
                rule.model_copy(update={"embedding": vector})
                for rule, vector in zip(document.policy_rules, vectors, strict=True)
            ]
        return document.model_copy(update=updates) if updates else document
