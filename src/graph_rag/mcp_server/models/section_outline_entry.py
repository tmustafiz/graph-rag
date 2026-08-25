from pydantic import BaseModel


class SectionOutlineEntry(BaseModel):
    """A parent or child reference in a section's outline."""

    id: str
    title: str
