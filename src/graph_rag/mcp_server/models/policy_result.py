from pydantic import BaseModel, Field


class PolicyResult(BaseModel):
    """One Checkov policy returned by `find_policies_for` or `search_policies`.

    From `search_policies`, hits are ordered by `score` (the fused relevance)
    unless `rerank_score` is present, in which case that is the ordering signal
    and `score` is retained only as the pre-rerank value. `find_policies_for` is
    an exact-match traversal and sets neither.
    """

    id: str
    name: str | None = None
    category: str | None = None
    severity: str | None = None
    guideline: str | None = None
    provider: str | None = None
    source_path: str | None = None
    resource_types: list[str] = Field(default_factory=list)
    # Set by `search_policies` (always `None` from `find_policies_for`): fused
    # vector + full-text relevance, min-max normalized to [0, 1]. Always the
    # ordering signal unless `rerank_score` is set.
    score: float | None = None
    # Raw cross-encoder logit (unbounded, can be negative), set only when
    # `GRAG_RERANK` is on. When present it is what the hits are ordered by;
    # `score` still carries the pre-rerank fused value.
    rerank_score: float | None = None
