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
    # vector+full-text relevance in [0, 1], or a raw cross-encoder logit
    # (unbounded, can be negative) when reranking is enabled.
    score: float | None = None
