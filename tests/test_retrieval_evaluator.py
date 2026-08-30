from graph_rag.eval import EvalCase, RetrievalEvaluator
from graph_rag.mcp_server.models import SearchResult


class _FakeRetriever:
    def __init__(self, hits: list[SearchResult]) -> None:
        self._hits = hits

    def search(
        self,
        query: str,
        top_k: int = 5,
        source_type: str | None = None,
        source_path: str | None = None,
    ) -> list[SearchResult]:
        return self._hits[:top_k]


def _hit(source_path: str, breadcrumb: str) -> SearchResult:
    return SearchResult(
        chunk_id="c1",
        text="irrelevant",
        breadcrumb=breadcrumb,
        source_path=source_path,
        source_type="pdf",
        score=1.0,
    )


def test_case_passes_when_expected_hit_is_first() -> None:
    breadcrumb = "Working with an AWS DMS replication instance > Creating a replication instance"
    hits = [_hit("service-guide.pdf", breadcrumb)]
    case = EvalCase(
        query="how do I create a replication instance",
        expected_source_path="service-guide.pdf",
        expected_breadcrumb_contains="Creating a replication instance",
    )

    results = RetrievalEvaluator(_FakeRetriever(hits)).run([case])

    assert results[0].passed is True
    assert results[0].best_rank == 1


def test_case_passes_when_expected_hit_is_not_first() -> None:
    hits = [
        _hit("other.pdf", "unrelated section"),
        _hit("service-guide.pdf", "Creating a replication instance"),
    ]
    case = EvalCase(
        query="how do I create a replication instance",
        expected_source_path="service-guide.pdf",
        expected_breadcrumb_contains="Creating a replication instance",
    )

    results = RetrievalEvaluator(_FakeRetriever(hits)).run([case])

    assert results[0].passed is True
    assert results[0].best_rank == 2


def test_case_fails_when_source_path_matches_but_breadcrumb_does_not() -> None:
    hits = [_hit("service-guide.pdf", "unrelated section")]
    case = EvalCase(
        query="how do I create a replication instance",
        expected_source_path="service-guide.pdf",
        expected_breadcrumb_contains="Creating a replication instance",
    )

    results = RetrievalEvaluator(_FakeRetriever(hits)).run([case])

    assert results[0].passed is False
    assert results[0].best_rank is None


def test_case_fails_when_no_hits() -> None:
    case = EvalCase(
        query="how do I create a replication instance",
        expected_source_path="service-guide.pdf",
        expected_breadcrumb_contains="Creating a replication instance",
    )

    results = RetrievalEvaluator(_FakeRetriever([])).run([case])

    assert results[0].passed is False


def test_load_cases_reads_the_built_in_eval_set() -> None:
    cases = RetrievalEvaluator.load_cases()
    assert len(cases) >= 5
    assert all(case.expected_source_path.startswith("src/graph_rag/eval/corpus/") for case in cases)
