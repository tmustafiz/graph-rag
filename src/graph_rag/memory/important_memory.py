from datetime import datetime

from pydantic import BaseModel


class ImportantMemory(BaseModel):
    """An `importance=True` `AgentMemory`, for the `prune-memory --list-important`
    review — these never decay, so a human should occasionally prune them by
    `forget`ting the ones that no longer matter.
    """

    id: str
    kind: str
    created_at: datetime
    last_accessed_at: datetime
    access_count: int
    content: str
