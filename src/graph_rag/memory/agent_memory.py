from datetime import datetime

from pydantic import BaseModel


class AgentMemory(BaseModel):
    """One piece of the coding agent's own working memory (a decision,
    correction, finding, preference, or fact) — independent of the
    document-ingestion pipeline; written one at a time, mid-session.
    """

    id: str
    content: str
    kind: str  # "decision" | "correction" | "finding" | "preference" | "fact"
    embed_text: str
    embedding: list[float] | None = None
    created_at: datetime
    last_accessed_at: datetime
    access_count: int = 0
    importance: bool = False
    archived_at: datetime | None = None
    source_session_id: str | None = None
    # The CodeEntity this memory is about, if any. Always stored as a plain
    # property — the source of truth for `MemoryRecaller.recall`'s
    # `about_qualified_name` filter, so it holds regardless of whether a
    # matching CodeEntity exists in this database. See `MemoryWriter` for the
    # best-effort `ABOUT` graph edge this also drives, which only forms
    # same-database.
    about_qualified_name: str | None = None
