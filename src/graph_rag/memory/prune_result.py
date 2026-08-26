from pydantic import BaseModel


class PruneResult(BaseModel):
    """Outcome of one `MemoryPruner.prune()` run."""

    soft_deleted: int
    hard_deleted: int
