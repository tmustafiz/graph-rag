from pydantic import BaseModel


class SearchResult(BaseModel):
    """One hybrid (vector + full-text) search hit, with citation context."""

    chunk_id: str
    text: str
    breadcrumb: str
    source_path: str
    source_type: str
    start_page: int | None = None
    end_page: int | None = None
    # Fused vector+full-text relevance in [0, 1] normally; a raw cross-encoder
    # logit (unbounded, can be negative) when reranking is enabled.
    score: float
