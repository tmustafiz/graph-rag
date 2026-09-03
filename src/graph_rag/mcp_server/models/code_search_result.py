from pydantic import BaseModel


class CodeSearchResult(BaseModel):
    """One hybrid (vector + full-text) search hit over `CodeEntity` nodes."""

    qualified_name: str
    name: str
    kind: str
    docstring: str | None = None
    signature: str | None = None
    file_path: str | None = None
    start_line: int | None = None
    end_line: int | None = None
    # Fused vector+full-text relevance in [0, 1] normally; a raw cross-encoder
    # logit (unbounded, can be negative) when reranking is enabled.
    score: float
