from pydantic import BaseModel, Field


class PruneResult(BaseModel):
    """Outcome of one `MemoryPruner.prune()` run.

    On a `dry_run` the id lists say what *would* be soft- / hard-deleted and
    nothing is written.
    """

    soft_deleted: list[str] = Field(default_factory=list)
    hard_deleted: list[str] = Field(default_factory=list)
    dry_run: bool = False

    @property
    def soft_deleted_count(self) -> int:
        return len(self.soft_deleted)

    @property
    def hard_deleted_count(self) -> int:
        return len(self.hard_deleted)
