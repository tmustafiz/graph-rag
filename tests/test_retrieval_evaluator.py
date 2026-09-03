import pytest

from graph_rag.eval import EvalCase, RetrievalEvaluator
from graph_rag.mcp_server.models import CodeSearchResult, PolicyResult, SearchResult


class _FakeRetriever:
    def __init__(
        self,
        hits: list[SearchResult] | None = None,
        code_hits: list[CodeSearchResult] | None = None,
        policy_hits: list[PolicyResult] | None = None,
    ) -> None:
        self._hits = hits or []
        self._code_hits = code_hits or []
        self._policy_hits = policy_hits or []

    def search(
        self,
        query: str,
        top_k: int = 5,
        source_type: str | None = None,
        source_path: str | None = None,
    ) -> list[SearchResult]:
        return self._hits[:top_k]

    def search_code(self, query: str, top_k: int = 5) -> list[CodeSearchResult]:
        return self._code_hits[:top_k]

    def search_policies(self, query: str, top_k: int = 5) -> list[PolicyResult]:
        return self._policy_hits[:top_k]


def _hit(source_path: str, breadcrumb: str) -> SearchResult:
    return SearchResult(
        chunk_id="c1",
        text="irrelevant",
        breadcrumb=breadcrumb,
        source_path=source_path,
        source_type="pdf",
        score=1.0,
    )


def _code_hit(qualified_name: str) -> CodeSearchResult:
    return CodeSearchResult(
        qualified_name=qualified_name,
        name=qualified_name.split(".")[-1],
        kind="function",
        score=1.0,
    )


def _policy_hit(policy_id: str) -> PolicyResult:
    return PolicyResult(id=policy_id, name=policy_id, score=1.0)


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


def test_search_code_case_matches_on_qualified_name_substring() -> None:
    case = EvalCase(
        query="reclaim tasks from a dead worker",
        tool="search_code",
        expected_qualified_name_contains="LeaseScheduler.reclaim_expired_leases",
    )
    retriever = _FakeRetriever(
        code_hits=[
            _code_hit("scheduler.Lease.is_expired"),
            _code_hit("scheduler.LeaseScheduler.reclaim_expired_leases"),
        ]
    )

    results = RetrievalEvaluator(retriever).run([case])

    assert results[0].passed is True
    assert results[0].best_rank == 2


def test_search_policies_case_matches_on_exact_id() -> None:
    case = EvalCase(
        query="require TLS from workers to the broker",
        tool="search_policies",
        expected_policy_id="ORCHARD_CUSTOM_2",
    )
    retriever = _FakeRetriever(
        policy_hits=[_policy_hit("ORCHARD_CUSTOM_1"), _policy_hit("ORCHARD_CUSTOM_2")]
    )

    results = RetrievalEvaluator(retriever).run([case])

    assert results[0].passed is True
    assert results[0].best_rank == 2


def test_negative_case_passes_when_expectation_is_absent() -> None:
    case = EvalCase(
        query="kubernetes ingress",
        expect_match=False,
        expected_source_path="service-guide.pdf",
        expected_breadcrumb_contains="Creating a replication instance",
    )

    passing = RetrievalEvaluator(_FakeRetriever([_hit("other.pdf", "something else")])).run([case])
    assert passing[0].passed is True
    assert passing[0].best_rank is None

    leaked = RetrievalEvaluator(
        _FakeRetriever([_hit("service-guide.pdf", "Creating a replication instance")])
    ).run([case])
    assert leaked[0].passed is False
    assert leaked[0].best_rank == 1


def test_eval_case_rejects_missing_expectation_fields_for_its_tool() -> None:
    with pytest.raises(ValueError, match="missing required field"):
        EvalCase(query="x", tool="search_code")


def test_load_cases_reads_the_built_in_eval_set() -> None:
    cases = RetrievalEvaluator.load_cases()

    assert len(cases) >= 5
    tools = {case.tool for case in cases}
    assert tools == {"search", "search_code", "search_policies"}
    assert any(not case.expect_match for case in cases), "expected at least one negative case"
    for case in cases:
        if case.tool == "search":
            assert case.expected_source_path.startswith("src/graph_rag/eval/corpus/")
