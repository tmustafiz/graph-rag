from datetime import UTC, datetime, timedelta

from graph_rag.memory.memory_pruner import MemoryPruner


def test_score_is_zero_for_never_accessed_memory() -> None:
    now = datetime.now(UTC)
    created_at = (now - timedelta(days=9)).isoformat()
    assert MemoryPruner._score(access_count=0, created_at=created_at, now=now) == 0.0


def test_score_decays_as_a_memory_ages_at_fixed_access_count() -> None:
    now = datetime.now(UTC)
    young = MemoryPruner._score(
        access_count=5, created_at=(now - timedelta(days=1)).isoformat(), now=now
    )
    old = MemoryPruner._score(
        access_count=5, created_at=(now - timedelta(days=99)).isoformat(), now=now
    )
    assert young > old


def test_score_increases_with_access_count_at_fixed_age() -> None:
    now = datetime.now(UTC)
    created_at = (now - timedelta(days=10)).isoformat()
    rarely_accessed = MemoryPruner._score(access_count=1, created_at=created_at, now=now)
    often_accessed = MemoryPruner._score(access_count=20, created_at=created_at, now=now)
    assert often_accessed > rarely_accessed


def test_score_for_brand_new_memory_uses_age_plus_one_floor() -> None:
    now = datetime.now(UTC)
    score = MemoryPruner._score(access_count=1, created_at=now.isoformat(), now=now)
    assert score == 1.0  # age_days ~ 0, so 1 / (0 + 1)
