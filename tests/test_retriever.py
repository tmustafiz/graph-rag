from neo4j.exceptions import ClientError

from graph_rag.mcp_server.retriever import (
    Retriever,
    _build_outline_tree,
    _code_document,
    _escape_lucene,
    _format_citation,
    _policy_document,
    _prose_document,
    combine_scores,
)


class _LengthReranker:
    """Stand-in cross-encoder: scores each document by its length, so a longer
    candidate string sorts ahead of a shorter one — deterministic and offline.
    """

    def rerank(self, query: str, documents: list[str]) -> list[float]:
        return [float(len(document)) for document in documents]


def _retriever_with_reranker(reranker: object) -> Retriever:
    return Retriever(driver=None, embedder=None, reranker=reranker)  # type: ignore[arg-type]


def test_maybe_rerank_is_a_passthrough_without_a_reranker() -> None:
    retriever = _retriever_with_reranker(None)
    fused = {"a": 0.9, "b": 0.4}
    ids, scores = retriever._maybe_rerank("q", ["a", "b"], {"a": "x", "b": "y"}, fused)
    assert ids == ["a", "b"]
    assert scores is fused


def test_maybe_rerank_reorders_by_cross_encoder_score() -> None:
    retriever = _retriever_with_reranker(_LengthReranker())
    fused = {"a": 0.9, "b": 0.4}
    ids, scores = retriever._maybe_rerank(
        "q", ["a", "b"], {"a": "short", "b": "much longer document"}, fused
    )
    assert ids == ["b", "a"]  # "b" has the longer document, so it wins
    assert scores == {"a": 5.0, "b": 20.0}


def test_maybe_rerank_handles_an_empty_shortlist() -> None:
    retriever = _retriever_with_reranker(_LengthReranker())
    assert retriever._maybe_rerank("q", [], {}, {}) == ([], {})


def test_prose_document_prepends_the_breadcrumb() -> None:
    row = {"breadcrumb": "Deployment > Environment variables", "text": "ORCHARD_BROKER_URL ..."}
    assert _prose_document(row) == "Deployment > Environment variables\n\nORCHARD_BROKER_URL ..."


def test_code_document_joins_present_fields_only() -> None:
    row = {"name": "reclaim", "signature": "(self)", "docstring": None}
    assert _code_document(row) == "reclaim (self)"


def test_policy_document_joins_name_and_guideline() -> None:
    row = {"name": "Reclaim stuck tasks", "guideline": "A queue must reclaim..."}
    assert _policy_document(row) == "Reclaim stuck tasks A queue must reclaim..."


def test_escape_lucene_neutralizes_metacharacters() -> None:
    assert _escape_lucene("Set-FSxSmbServerConfiguration") == r"Set\-FSxSmbServerConfiguration"
    assert _escape_lucene("ingest --dry-run") == r"ingest \-\-dry\-run"
    assert _escape_lucene("resource:aws_db_instance") == r"resource\:aws_db_instance"
    assert _escape_lucene("call foo() then bar()") == r"call foo\(\) then bar\(\)"
    assert _escape_lucene("a && b || !c") == r"a \&\& b \|\| \!c"


def test_escape_lucene_leaves_plain_text_untouched() -> None:
    assert _escape_lucene("how do I create a queue") == "how do I create a queue"


class _RaisingSession:
    def run(self, *_args: object, **_kwargs: object) -> object:
        raise ClientError("Encountered ' - ' at line 1")


class _RowsSession:
    def run(self, *_args: object, **_kwargs: object) -> list[dict[str, object]]:
        return [{"chunk_id": "c1", "score": 3.0}, {"chunk_id": "c2", "score": 1.0}]


def test_fulltext_scores_degrades_to_empty_on_parser_error() -> None:
    scores = Retriever._fulltext_scores(_RaisingSession(), "CYPHER", {"query": "a-b"}, "chunk_id")
    assert scores == {}


def test_fulltext_scores_returns_score_map_on_success() -> None:
    scores = Retriever._fulltext_scores(_RowsSession(), "CYPHER", {"query": "ab"}, "chunk_id")
    assert scores == {"c1": 3.0, "c2": 1.0}


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
        "source_path": "docs/service-guide.pdf",
        "breadcrumb": "Concepts > Selection rules",
        "start_page": 42,
        "end_page": 42,
    }
    citation = _format_citation(row)
    assert citation == "docs/service-guide.pdf — Concepts > Selection rules (p. 42)"


def test_format_citation_includes_page_range() -> None:
    row = {
        "source_path": "docs/service-guide.pdf",
        "breadcrumb": "Concepts > Selection rules",
        "start_page": 42,
        "end_page": 44,
    }
    citation = _format_citation(row)
    assert citation == "docs/service-guide.pdf — Concepts > Selection rules (pp. 42–44)"


def test_format_citation_omits_pages_when_absent() -> None:
    row = {
        "source_path": "src/graph_rag/cli.py",
        "breadcrumb": "graph_rag.cli.status",
        "start_page": None,
        "end_page": None,
    }
    citation = _format_citation(row)
    assert citation == "src/graph_rag/cli.py — graph_rag.cli.status"
