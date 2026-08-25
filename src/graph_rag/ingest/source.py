from datetime import datetime

from pydantic import BaseModel


class Source(BaseModel):
    """One ingested file (`Source.path` is the unique key in the graph)."""

    path: str
    source_type: str
    content_hash: str
    ingested_at: datetime
    version: int = 1
