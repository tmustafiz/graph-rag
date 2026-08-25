from pydantic import BaseModel


class Section(BaseModel):
    """Hierarchical heading node (e.g. a PDF outline entry or Markdown heading)."""

    id: str
    title: str
    level: int
    breadcrumb: str
    order: int
    parent_id: str | None = None
    start_page: int | None = None
    end_page: int | None = None
