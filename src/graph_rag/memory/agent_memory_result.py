from datetime import datetime

from pydantic import BaseModel


class AgentMemoryResult(BaseModel):
    """One `MemoryRecaller.recall()` hit.

    `last_accessed_at` and `access_count` are returned so the caller can judge
    how stale — or how reinforced — a memory is, and feed that back into the
    ranking (see `MemoryRecaller`).
    """

    id: str
    content: str
    kind: str
    created_at: datetime
    last_accessed_at: datetime
    access_count: int
    importance: bool
    score: float
