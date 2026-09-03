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
    # Fused vector + full-text relevance, min-max normalized to [0, 1]. Always
    # the ordering signal unless `rerank_score` is set.
    score: float
    # Raw cross-encoder logit (unbounded, can be negative), set only when
    # `GRAG_RERANK` is on. When present it is what the hits are ordered by;
    # `score` still carries the pre-rerank fused value.
    rerank_score: float | None = None
