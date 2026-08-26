from pydantic import BaseModel


class IngestRequest(BaseModel):
    """Request body for `POST /ingest`."""

    path: str
    dry_run: bool = False
