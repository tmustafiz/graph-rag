from pydantic import BaseModel


class Chunk(BaseModel):
    """Atomic retrievable unit of text belonging to a single `Section`."""

    id: str
    section_id: str
    order: int
    text: str
    token_count: int
    content_hash: str
    start_page: int | None = None
    end_page: int | None = None
    embedding: list[float] | None = None
