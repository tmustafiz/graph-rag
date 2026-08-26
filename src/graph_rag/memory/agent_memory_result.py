from datetime import datetime

from pydantic import BaseModel


class AgentMemoryResult(BaseModel):
    """One `MemoryRecaller.recall()` hit."""

    id: str
    content: str
    kind: str
    created_at: datetime
    importance: bool
    score: float
