from pathlib import Path

from pydantic import BaseModel


class IngestionResult(BaseModel):
    """Outcome of ingesting one file via `IngestionPipeline`."""

    path: Path
    skipped: bool
    sections: int = 0
    chunks: int = 0
    code_entities: int = 0
    policy_rules: int = 0
