from datetime import UTC, datetime, timedelta

from graph_rag.memory.memory_recaller import (
    _FULLTEXT_SEARCH_MEMORY,
    _VECTOR_SEARCH_MEMORY,
    IMPORTANCE_BOOST,
    _combine_scores,
    _final_scores,
    _reinforcement,
)

_NOW = datetime(2026, 9, 3, tzinfo=UTC)


def test_vector_search_filters_about_by_property_not_a_graph_edge() -> None:
    # A pattern-match filter (`(m)-[:ABOUT]->(:CodeEntity {...})`) can never
    # match in a database with no CodeEntity nodes at all (a memory-only
    # deployment) — the filter must be a plain property comparison so
    # `about_qualified_name` still works there.
    assert "m.about_qualified_name = $about" in _VECTOR_SEARCH_MEMORY
    assert "ABOUT" not in _VECTOR_SEARCH_MEMORY
    assert "CodeEntity" not in _VECTOR_SEARCH_MEMORY


def test_fulltext_search_filters_about_by_property_not_a_graph_edge() -> None:
    assert "m.about_qualified_name = $about" in _FULLTEXT_SEARCH_MEMORY
    assert "ABOUT" not in _FULLTEXT_SEARCH_MEMORY
    assert "CodeEntity" not in _FULLTEXT_SEARCH_MEMORY


def test_combine_scores_ranks_pure_vector_hit_by_normalized_similarity() -> None:
    scores = _combine_scores({"a": 0.9, "b": 0.5}, {})
    assert scores["a"] == 0.7  # normalized to 1.0, weighted by VECTOR_WEIGHT
    assert scores["b"] == 0.0  # normalized to 0.0 (the minimum)


def test_combine_scores_boosts_a_fulltext_hit() -> None:
    vector_only = _combine_scores({"a": 0.9, "b": 0.5}, {})
    boosted = _combine_scores({"a": 0.9, "b": 0.5}, {"b": 5.0})
    assert boosted["b"] > vector_only["b"]
    assert boosted["a"] == vector_only["a"]  # "a" has no fulltext hit, unaffected


def test_combine_scores_ignores_fulltext_only_hits() -> None:
    # A memory id only present in fulltext (never a vector candidate) isn't returned —
    # the vector search result set defines which memories are eligible.
    scores = _combine_scores({"a": 0.9}, {"a": 1.0, "z": 5.0})
    assert set(scores) == {"a"}


def test_combine_scores_empty_input() -> None:
    assert _combine_scores({}, {}) == {}


def test_reinforcement_is_zero_for_a_never_recalled_memory() -> None:
    assert _reinforcement(0, _NOW, _NOW) == 0.0


def test_reinforcement_rises_with_access_count_and_decays_with_age() -> None:
    fresh_often = _reinforcement(8, _NOW, _NOW)
    fresh_once = _reinforcement(1, _NOW, _NOW)
    stale_often = _reinforcement(8, _NOW - timedelta(days=90), _NOW)

    assert 0.0 < fresh_once < fresh_often <= 1.0
    assert stale_often < fresh_often
    assert _reinforcement(8, (_NOW - timedelta(days=90)).isoformat(), _NOW) == stale_often


def _row(importance: bool = False, access_count: int = 0, last_days_ago: int = 0) -> dict:
    return {
        "importance": importance,
        "access_count": access_count,
        "last_accessed_at": _NOW - timedelta(days=last_days_ago),
    }


def test_final_scores_applies_a_flat_importance_boost() -> None:
    rows = {"a": _row(importance=True), "b": _row(importance=False)}
    final = _final_scores({"a": 0.5, "b": 0.5}, rows, _NOW)
    assert final["a"] == 0.5 + IMPORTANCE_BOOST
    assert final["b"] == 0.5


def test_final_scores_can_lift_a_reinforced_memory_over_a_slightly_better_one() -> None:
    rows = {"reinforced": _row(access_count=10, last_days_ago=0), "cold": _row()}
    final = _final_scores({"reinforced": 0.55, "cold": 0.60}, rows, _NOW)
    assert final["reinforced"] > final["cold"]


def test_final_scores_does_not_let_boosts_override_a_large_relevance_gap() -> None:
    rows = {"weak_but_flagged": _row(importance=True, access_count=10), "strong": _row()}
    final = _final_scores({"weak_but_flagged": 0.30, "strong": 0.90}, rows, _NOW)
    assert final["strong"] > final["weak_but_flagged"]
