from graph_rag.memory.memory_recaller import _combine_scores


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
