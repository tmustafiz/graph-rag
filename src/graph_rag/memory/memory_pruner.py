from datetime import UTC, datetime, timedelta
from typing import LiteralString, cast

from neo4j import Driver, ManagedTransaction

from .prune_result import PruneResult

_FIND_PRUNE_CANDIDATES = """
MATCH (m:AgentMemory)
WHERE m.archived_at IS NULL AND m.importance = false
RETURN m.id AS id, m.access_count AS access_count, m.created_at AS created_at
"""

_SOFT_DELETE = """
UNWIND $ids AS id
MATCH (m:AgentMemory {id: id})
SET m.archived_at = $archived_at
"""

_HARD_DELETE_EXPIRED = """
MATCH (m:AgentMemory)
WHERE m.archived_at IS NOT NULL AND m.archived_at <= $cutoff
WITH collect(m) AS stale, count(m) AS deleted
UNWIND stale AS m
DETACH DELETE m
RETURN deleted
"""

DEFAULT_GRACE_DAYS = 30


class MemoryPruner:
    """Soft-deletes low recency+frequency-score `AgentMemory` nodes, then
    hard-deletes anything that's been archived past the grace window.

    A memory with `importance=True` is exempt from decay-based soft-delete
    regardless of its score, but is still hard-deleted once archived (e.g.
    via `MemoryWriter.forget`) and past the grace window.
    """

    def __init__(self, driver: Driver) -> None:
        self._driver = driver

    def prune(self, threshold: float, grace_days: int = DEFAULT_GRACE_DAYS) -> PruneResult:
        now = datetime.now(UTC)
        with self._driver.session() as session:
            candidates = list(session.run(cast(LiteralString, _FIND_PRUNE_CANDIDATES)))
            stale_ids = [
                row["id"]
                for row in candidates
                if self._score(row["access_count"], row["created_at"], now) < threshold
            ]
            if stale_ids:
                session.execute_write(self._soft_delete, stale_ids, now)

            cutoff = (now - timedelta(days=grace_days)).isoformat()
            hard_deleted = session.execute_write(self._hard_delete_expired, cutoff)

        return PruneResult(soft_deleted=len(stale_ids), hard_deleted=hard_deleted)

    @staticmethod
    def _score(access_count: int, created_at: str, now: datetime) -> float:
        age_days = (now - datetime.fromisoformat(created_at)).total_seconds() / 86400
        return access_count / (age_days + 1)

    @staticmethod
    def _soft_delete(tx: ManagedTransaction, ids: list[str], archived_at: datetime) -> None:
        tx.run(cast(LiteralString, _SOFT_DELETE), ids=ids, archived_at=archived_at.isoformat())

    @staticmethod
    def _hard_delete_expired(tx: ManagedTransaction, cutoff: str) -> int:
        record = tx.run(cast(LiteralString, _HARD_DELETE_EXPIRED), cutoff=cutoff).single()
        return record["deleted"] if record else 0
