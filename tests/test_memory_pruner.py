import math
from datetime import UTC, datetime, timedelta

from graph_rag.memory import PruneResult
from graph_rag.memory.memory_pruner import DEFAULT_TAU_DAYS, DEFAULT_THRESHOLD, MemoryPruner

_NOW = datetime(2026, 9, 3, tzinfo=UTC)


def _score(access_count: int, last_days_ago: float) -> float:
    last = (_NOW - timedelta(days=last_days_ago)).isoformat()
    return MemoryPruner._score(access_count, last, _NOW, DEFAULT_TAU_DAYS)


def test_score_of_a_just_saved_never_recalled_memory_is_one() -> None:
    assert _score(access_count=0, last_days_ago=0) == 1.0


def test_score_decays_with_time_since_last_recall() -> None:
    assert _score(5, last_days_ago=1) > _score(5, last_days_ago=99)


def test_score_rises_with_access_count_at_fixed_recency() -> None:
    assert _score(20, last_days_ago=10) > _score(1, last_days_ago=10)


def test_score_accepts_a_datetime_as_well_as_an_iso_string() -> None:
    as_dt = MemoryPruner._score(3, _NOW - timedelta(days=5), _NOW, DEFAULT_TAU_DAYS)
    as_str = MemoryPruner._score(3, (_NOW - timedelta(days=5)).isoformat(), _NOW, DEFAULT_TAU_DAYS)
    assert as_dt == as_str == 4 * math.exp(-5 / DEFAULT_TAU_DAYS)


def test_default_threshold_prunes_a_never_recalled_memory_after_about_three_weeks() -> None:
    # (1 + 0) * exp(-t/30) < 0.5  <=>  t > 30 * ln(2) ~ 20.8 days
    assert _score(0, last_days_ago=20) > DEFAULT_THRESHOLD
    assert _score(0, last_days_ago=22) < DEFAULT_THRESHOLD


class _FakeSession:
    def __init__(self, candidates: list[dict], expired: list[dict]) -> None:
        self._responses = [candidates, expired]
        self.writes = 0

    def __enter__(self) -> "_FakeSession":
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def run(self, _cypher: str, **_kwargs: object) -> list[dict]:
        return self._responses.pop(0)

    def execute_write(self, *_args: object) -> None:
        self.writes += 1


class _FakeDriver:
    def __init__(self, session: _FakeSession) -> None:
        self._session = session

    def session(self) -> _FakeSession:
        return self._session


def test_dry_run_reports_candidates_but_writes_nothing() -> None:
    stale = (_NOW - timedelta(days=90)).isoformat()
    session = _FakeSession(
        candidates=[{"id": "m1", "access_count": 0, "last_accessed_at": stale}],
        expired=[{"id": "old1"}],
    )
    pruner = MemoryPruner(_FakeDriver(session))  # type: ignore[arg-type]

    result = pruner.prune(dry_run=True)

    assert result == PruneResult(soft_deleted=["m1"], hard_deleted=["old1"], dry_run=True)
    assert result.soft_deleted_count == 1
    assert result.hard_deleted_count == 1
    assert session.writes == 0


def test_non_dry_run_writes_soft_and_hard_deletes() -> None:
    stale = (_NOW - timedelta(days=90)).isoformat()
    session = _FakeSession(
        candidates=[{"id": "m1", "access_count": 0, "last_accessed_at": stale}],
        expired=[{"id": "old1"}],
    )
    pruner = MemoryPruner(_FakeDriver(session))  # type: ignore[arg-type]

    result = pruner.prune()

    assert result.soft_deleted == ["m1"]
    assert result.hard_deleted == ["old1"]
    assert session.writes == 2  # one soft-delete write, one hard-delete write
