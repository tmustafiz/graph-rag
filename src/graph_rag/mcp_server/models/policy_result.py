from pydantic import BaseModel, Field


class PolicyResult(BaseModel):
    """One Checkov policy returned by the `find_policies_for` tool."""

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
