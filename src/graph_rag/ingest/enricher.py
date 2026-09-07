from .embedders import Embedder
from .models import ParsedDocument


class Enricher:
    """Fills in the `embedding` field for every chunk / code entity / policy rule /
    DB table / DB view / HTTP endpoint in a document."""

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
        if document.db_tables:
            vectors = self._embedder.embed([table.embed_text for table in document.db_tables])
            updates["db_tables"] = [
                table.model_copy(update={"embedding": vector})
                for table, vector in zip(document.db_tables, vectors, strict=True)
            ]
        if document.db_views:
            vectors = self._embedder.embed([view.embed_text for view in document.db_views])
            updates["db_views"] = [
                view.model_copy(update={"embedding": vector})
                for view, vector in zip(document.db_views, vectors, strict=True)
            ]
        if document.http_endpoints:
            vectors = self._embedder.embed(
                [endpoint.embed_text for endpoint in document.http_endpoints]
            )
            updates["http_endpoints"] = [
                endpoint.model_copy(update={"embedding": vector})
                for endpoint, vector in zip(document.http_endpoints, vectors, strict=True)
            ]
        return document.model_copy(update=updates) if updates else document
