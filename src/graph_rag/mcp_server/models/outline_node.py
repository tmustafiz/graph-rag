from pydantic import BaseModel, Field


class OutlineNode(BaseModel):
    """One entry in a source's section outline (table of contents)."""

    id: str
    title: str
    children: list["OutlineNode"] = Field(default_factory=list)
