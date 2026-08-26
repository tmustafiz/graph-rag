from pathlib import Path

from pydantic import BaseModel


class IngestionResult(BaseModel):
    """Outcome of ingesting one file via `IngestionPipeline`.

    `error` is set (and every count left at 0) when parsing/embedding/writing
    that one file raised — the run continues on to the rest of the batch
    rather than aborting.
    """

    path: Path
    skipped: bool
    sections: int = 0
    chunks: int = 0
    code_entities: int = 0
    policy_rules: int = 0
    error: str | None = None
