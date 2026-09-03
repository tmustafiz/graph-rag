import math
from datetime import UTC, datetime, timedelta
from typing import LiteralString, cast

from neo4j import Driver, ManagedTransaction

from .important_memory import ImportantMemory
from .prune_result import PruneResult

_FIND_PRUNE_CANDIDATES = """
MATCH (m:AgentMemory)
WHERE m.archived_at IS NULL AND m.importance = false
RETURN m.id AS id, m.access_count AS access_count, m.last_accessed_at AS last_accessed_at
"""

_SOFT_DELETE = """
UNWIND $ids AS id
MATCH (m:AgentMemory {id: id})
SET m.archived_at = $archived_at
"""

_FIND_HARD_DELETE_EXPIRED = """
MATCH (m:AgentMemory)
WHERE m.archived_at IS NOT NULL AND m.archived_at <= $cutoff
RETURN m.id AS id
"""

_HARD_DELETE = """
UNWIND $ids AS id
MATCH (m:AgentMemory {id: id})
DETACH DELETE m
"""

_LIST_IMPORTANT = """
MATCH (m:AgentMemory)
WHERE m.archived_at IS NULL AND m.importance = true
RETURN m.id AS id, m.kind AS kind, m.created_at AS created_at,
       m.last_accessed_at AS last_accessed_at, m.access_count AS access_count,
       m.content AS content
ORDER BY m.created_at
"""

# Time (days) for the recency term to decay by 1/e. A memory not recalled for
# ~TAU is worth roughly a third of a freshly-recalled one at the same
# access_count.
DEFAULT_TAU_DAYS = 30.0
# Below this score a non-important memory is soft-deleted. At the default TAU a
# never-recalled memory crosses it ~21 days after creation; one recalled once
# lasts ~42 days past its last recall; one recalled 5+ times lasts months.
DEFAULT_THRESHOLD = 0.5
DEFAULT_GRACE_DAYS = 30


class MemoryPruner:
    """Soft-deletes low-scoring `AgentMemory` nodes, then hard-deletes anything
    archived past the grace window.

    Score is `(1 + access_count) * exp(-days_since_last_recall / TAU)` — a
    memory the agent keeps coming back to survives; one it saved and never
    revisited decays out. `importance=True` memories are exempt from
    decay-based soft-delete (review them with `prune-memory --list-important`)
    but are still hard-deleted once archived (e.g. via `forget`) and past the
    grace window.
    """

    def __init__(self, driver: Driver) -> None:
        self._driver = driver

    def prune(
        self,
        threshold: float = DEFAULT_THRESHOLD,
        grace_days: int = DEFAULT_GRACE_DAYS,
        tau_days: float = DEFAULT_TAU_DAYS,
        dry_run: bool = False,
    ) -> PruneResult:
        now = datetime.now(UTC)
        cutoff = (now - timedelta(days=grace_days)).isoformat()
        with self._driver.session() as session:
            stale_ids = [
                row["id"]
                for row in session.run(cast(LiteralString, _FIND_PRUNE_CANDIDATES))
                if self._score(row["access_count"], row["last_accessed_at"], now, tau_days)
                < threshold
            ]
            expired_ids = [
                row["id"]
                for row in session.run(
                    cast(LiteralString, _FIND_HARD_DELETE_EXPIRED), cutoff=cutoff
                )
            ]
            if not dry_run:
                if stale_ids:
                    session.execute_write(self._soft_delete, stale_ids, now)
                # Re-scan: a memory soft-deleted just now can't be past the grace
                # window, so `expired_ids` computed before the write still holds.
                if expired_ids:
                    session.execute_write(self._hard_delete, expired_ids)

        return PruneResult(soft_deleted=stale_ids, hard_deleted=expired_ids, dry_run=dry_run)

    def list_important(self) -> list[ImportantMemory]:
        with self._driver.session() as session:
            return [
                ImportantMemory.model_validate(dict(row))
                for row in session.run(cast(LiteralString, _LIST_IMPORTANT))
            ]

    @staticmethod
    def _score(
        access_count: int, last_accessed_at: str | datetime, now: datetime, tau_days: float
    ) -> float:
        last_accessed = (
            last_accessed_at
            if isinstance(last_accessed_at, datetime)
            else datetime.fromisoformat(last_accessed_at)
        )
        age_days = max((now - last_accessed).total_seconds() / 86400, 0.0)
        return (1 + max(access_count, 0)) * math.exp(-age_days / tau_days)

    @staticmethod
    def _soft_delete(tx: ManagedTransaction, ids: list[str], archived_at: datetime) -> None:
        tx.run(cast(LiteralString, _SOFT_DELETE), ids=ids, archived_at=archived_at.isoformat())

    @staticmethod
    def _hard_delete(tx: ManagedTransaction, ids: list[str]) -> None:
        tx.run(cast(LiteralString, _HARD_DELETE), ids=ids)
