from pydantic import BaseModel


class CodeSearchResult(BaseModel):
    """One hybrid (vector + full-text) search hit over `CodeEntity` nodes.

    Hits are ordered by `score` (the fused relevance) unless `rerank_score` is
    present, in which case that is the ordering signal and `score` is retained
    only as the pre-rerank value.
    """

    qualified_name: str
    name: str
    kind: str
    docstring: str | None = None
    signature: str | None = None
    file_path: str | None = None
    start_line: int | None = None
    end_line: int | None = None
    # Fused vector + full-text relevance, min-max normalized to [0, 1]. Always
    # the ordering signal unless `rerank_score` is set.
    score: float
    # Raw cross-encoder logit (unbounded, can be negative), set only when
    # `GRAG_RERANK` is on. When present it is what the hits are ordered by;
    # `score` still carries the pre-rerank fused value.
    rerank_score: float | None = None
