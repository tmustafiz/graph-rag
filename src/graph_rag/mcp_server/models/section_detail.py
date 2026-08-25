from pydantic import BaseModel, Field

from .section_outline_entry import SectionOutlineEntry


class SectionDetail(BaseModel):
    """Full text of one section, plus enough outline to navigate from it."""

    id: str
    title: str
    breadcrumb: str
    source_path: str
    text: str
    parent: SectionOutlineEntry | None = None
    children: list[SectionOutlineEntry] = Field(default_factory=list)
