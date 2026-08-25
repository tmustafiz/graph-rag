from pydantic import BaseModel, Field


class PolicyRule(BaseModel):
    """A Checkov custom policy (`PolicyRule.id` is the unique key in the graph)."""

    id: str
    name: str | None = None
    category: str | None = None
    severity: str | None = None
    guideline: str | None = None
    provider: str | None = None
    file_path: str | None = None
    embed_text: str
    resource_types: list[str] = Field(default_factory=list)
    embedding: list[float] | None = None
