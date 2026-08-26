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
