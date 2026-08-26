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
    score: float | None = None  # set by `search_policies`; always `None` from `find_policies_for`
