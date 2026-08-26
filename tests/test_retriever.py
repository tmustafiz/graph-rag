from graph_rag.mcp_server.retriever import _build_outline_tree, _format_citation, combine_scores


def test_combine_scores_ranks_pure_vector_hit_by_normalized_similarity() -> None:
    scores = combine_scores({"a": 0.9, "b": 0.5}, {})
    assert scores["a"] == 0.7  # normalized to 1.0, weighted by VECTOR_WEIGHT
    assert scores["b"] == 0.0  # normalized to 0.0 (the minimum)


def test_combine_scores_boosts_a_fulltext_hit() -> None:
    vector_only = combine_scores({"a": 0.9, "b": 0.5}, {})
    boosted = combine_scores({"a": 0.9, "b": 0.5}, {"b": 5.0})
    assert boosted["b"] > vector_only["b"]
    assert boosted["a"] == vector_only["a"]  # "a" has no fulltext hit, unaffected


def test_combine_scores_ignores_fulltext_only_hits() -> None:
    # A chunk_id only present in fulltext (never a vector candidate) isn't returned —
    # the vector search result set defines which chunks are eligible.
    scores = combine_scores({"a": 0.9}, {"a": 1.0, "z": 5.0})
    assert set(scores) == {"a"}


def test_combine_scores_handles_single_candidate() -> None:
    scores = combine_scores({"a": 0.42}, {})
    assert scores["a"] == 0.7  # sole candidate normalizes to 1.0


def test_combine_scores_empty_input() -> None:
    assert combine_scores({}, {}) == {}


def test_build_outline_tree_nests_children_under_their_parent() -> None:
    rows = [
        {"id": "s1", "title": "Concepts", "order": 0, "parent_id": None},
        {"id": "s2", "title": "Selection rules", "order": 1, "parent_id": "s1"},
        {"id": "s3", "title": "Transformation rules", "order": 2, "parent_id": "s1"},
    ]

    tree = _build_outline_tree(rows)

    assert [root.id for root in tree] == ["s1"]
    assert [child.id for child in tree[0].children] == ["s2", "s3"]


def test_build_outline_tree_returns_multiple_roots_when_no_hierarchy() -> None:
    rows = [
        {"id": "s1", "title": "Intro", "order": 0, "parent_id": None},
        {"id": "s2", "title": "Usage", "order": 1, "parent_id": None},
    ]

    tree = _build_outline_tree(rows)

    assert [root.id for root in tree] == ["s1", "s2"]
    assert tree[0].children == []


def test_build_outline_tree_handles_no_sections() -> None:
    assert _build_outline_tree([]) == []


def test_format_citation_includes_single_page() -> None:
    row = {
        "source_path": "training-docs/dms-ug.pdf",
        "breadcrumb": "Concepts > Selection rules",
        "start_page": 42,
        "end_page": 42,
    }
    citation = _format_citation(row)
    assert citation == "training-docs/dms-ug.pdf — Concepts > Selection rules (p. 42)"


def test_format_citation_includes_page_range() -> None:
    row = {
        "source_path": "training-docs/dms-ug.pdf",
        "breadcrumb": "Concepts > Selection rules",
        "start_page": 42,
        "end_page": 44,
    }
    citation = _format_citation(row)
    assert citation == "training-docs/dms-ug.pdf — Concepts > Selection rules (pp. 42–44)"


def test_format_citation_omits_pages_when_absent() -> None:
    row = {
        "source_path": "src/graph_rag/cli.py",
        "breadcrumb": "graph_rag.cli.status",
        "start_page": None,
        "end_page": None,
    }
    citation = _format_citation(row)
    assert citation == "src/graph_rag/cli.py — graph_rag.cli.status"
