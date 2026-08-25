from datetime import datetime

from pydantic import BaseModel


class SourceInfo(BaseModel):
    """One entry in the `list_sources` tool's inventory of ingested files."""

    path: str
    source_type: str
    ingested_at: datetime
    version: int
