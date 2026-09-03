"""Fictional lease scheduler used only as fixture content for the retrieval
regression eval (`grag-mcp eval-retrieval`). Nothing here is wired into the
real application; it exists so `search_code` has code to retrieve.

The model: a queue hands a task to a worker as a *lease* with a deadline. If
the worker does not acknowledge before the deadline the lease *expires* and the
task becomes available again, with its attempt counter incremented.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta


@dataclass
class Lease:
    """A task handed to a worker, owned until `deadline`."""

    task_id: str
    worker_id: str
    deadline: datetime
    attempts: int = 1

    def is_expired(self, now: datetime) -> bool:
        """True once `now` is past the lease deadline and the worker has lost
        ownership of the task.
        """
        return now >= self.deadline


@dataclass
class LeaseScheduler:
    """Tracks outstanding leases and decides which tasks may be handed out.

    A single-writer component: all mutation goes through these methods so the
    attempt counter and the visibility timeout stay consistent.
    """

    visibility_timeout: timedelta
    max_attempts: int = 5
    _leases: dict[str, Lease] = field(default_factory=dict)

    def grant_lease(self, task_id: str, worker_id: str, now: datetime) -> Lease:
        """Hand `task_id` to `worker_id` with a fresh deadline one
        `visibility_timeout` in the future. Re-granting a task that is already
        leased carries its attempt count forward.
        """
        previous = self._leases.get(task_id)
        attempts = previous.attempts + 1 if previous is not None else 1
        lease = Lease(task_id, worker_id, now + self.visibility_timeout, attempts)
        self._leases[task_id] = lease
        return lease

    def acknowledge(self, task_id: str) -> None:
        """Mark the task done and drop its lease. A no-op if the lease already
        expired and was reclaimed.
        """
        self._leases.pop(task_id, None)

    def reclaim_expired_leases(self, now: datetime) -> list[str]:
        """Drop every lease whose deadline has passed and return the task ids
        that are now available for re-granting. This is how a crashed worker's
        tasks get back into circulation.
        """
        expired = [task_id for task_id, lease in self._leases.items() if lease.is_expired(now)]
        for task_id in expired:
            del self._leases[task_id]
        return expired

    def is_poisoned(self, task_id: str) -> bool:
        """True when a task has been attempted `max_attempts` times without an
        acknowledgement and should go to the dead-letter queue instead of being
        retried again.
        """
        lease = self._leases.get(task_id)
        return lease is not None and lease.attempts >= self.max_attempts
