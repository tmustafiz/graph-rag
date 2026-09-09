"""#152 — the GDS projection must only name relationship types / node labels
that exist, so `compute-centrality` scores instead of throwing on a plain
(non-Spring) or pre-v0.7.0 database.

No live Neo4j in the test suite; `_FakeSession` answers the token-store probes
and captures the `gds.graph.project` arguments.
"""

from graph_rag.graph.centrality_analyzer import CentralityAnalyzer


class _Record:
    def __init__(self, data: dict[str, object]) -> None:
        self._data = data

    def __getitem__(self, key: str) -> object:
        return self._data[key]


class _FakeSession:
    def __init__(self, present_types: list[str], present_labels: list[str]) -> None:
        self._types = present_types
        self._labels = present_labels
        self.project_kwargs: dict[str, object] | None = None
        self.dropped = False

    def __enter__(self) -> "_FakeSession":
        return self

    def __exit__(self, *_exc: object) -> bool:
        return False

    def run(self, query: str, **params: object):  # noqa: ANN201
        if "db.relationshipTypes()" in query:
            return _Single({"types": self._types})
        if "db.labels()" in query:
            return _Single({"labels": self._labels})
        if "gds.graph.project" in query:
            self.project_kwargs = params
            return _Single({"nodeCount": 3, "relationshipCount": 5})
        if "gds.pageRank.write" in query:
            return _Single({"nodePropertiesWritten": 3})
        if "count(c) AS scored" in query:
            return _Single({"scored": 3})
        if "gds.graph.drop" in query:
            self.dropped = True
            return _Single({})
        raise AssertionError(f"unexpected query: {query}")


class _Single:
    def __init__(self, data: dict[str, object]) -> None:
        self._data = data

    def single(self) -> _Record:
        return _Record(self._data)


class _FakeDriver:
    def __init__(self, session: _FakeSession) -> None:
        self._session = session

    def session(self) -> _FakeSession:
        return self._session


def test_projection_names_only_types_and_labels_that_exist() -> None:
    session = _FakeSession(present_types=["CALLS", "IMPORTS"], present_labels=["CodeEntity"])
    scored = CentralityAnalyzer(_FakeDriver(session)).compute_code_pagerank()  # type: ignore[arg-type]

    assert scored == 3
    assert session.dropped
    assert session.project_kwargs is not None
    assert session.project_kwargs["labels"] == ["CodeEntity"]
    assert set(session.project_kwargs["relationships"]) == {"CALLS", "IMPORTS"}


def test_framework_types_are_projected_undirected_when_present() -> None:
    session = _FakeSession(
        present_types=["CALLS", "IMPORTS", "IS_BEAN", "EXECUTES"],
        present_labels=["CodeEntity", "Bean", "SqlStatement"],
    )
    CentralityAnalyzer(_FakeDriver(session)).compute_code_pagerank()  # type: ignore[arg-type]

    relationships = session.project_kwargs["relationships"]  # type: ignore[index]
    assert relationships["CALLS"] == {"orientation": "NATURAL"}
    assert relationships["IS_BEAN"] == {"orientation": "UNDIRECTED"}
    assert relationships["EXECUTES"] == {"orientation": "UNDIRECTED"}
    assert set(session.project_kwargs["labels"]) == {"CodeEntity", "Bean", "SqlStatement"}  # type: ignore[index]


def test_no_direct_edges_returns_zero_without_projecting() -> None:
    session = _FakeSession(present_types=["ANNOTATED_WITH"], present_labels=["CodeEntity"])
    assert CentralityAnalyzer(_FakeDriver(session)).compute_code_pagerank() == 0  # type: ignore[arg-type]
    assert session.project_kwargs is None
