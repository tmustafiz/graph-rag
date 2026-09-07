"""Unit tests for the Spring-aware retriever methods, driven by a fake Neo4j
session (the suite has no live Neo4j — matches `test_retriever.py`).
"""

from typing import Any

from graph_rag.mcp_server.retriever import Retriever, _bean_edges, _glob_to_regex


class _FakeResult:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def __iter__(self):
        return iter(self._rows)

    def single(self) -> dict[str, Any] | None:
        return self._rows[0] if self._rows else None


class _FakeSession:
    def __init__(self, responder) -> None:
        self._responder = responder
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def __enter__(self) -> "_FakeSession":
        return self

    def __exit__(self, *_exc: object) -> bool:
        return False

    def run(self, cypher: str, *args: Any, **kwargs: Any) -> _FakeResult:
        params = dict(args[0]) if args and isinstance(args[0], dict) else dict(kwargs)
        self.calls.append((cypher, params))
        return _FakeResult(self._responder(cypher, params))


class _FakeDriver:
    def __init__(self, responder) -> None:
        self.session_obj = _FakeSession(responder)

    def session(self) -> _FakeSession:
        return self.session_obj


class _ZeroEmbedder:
    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.0, 0.0, 0.0] for _ in texts]


def _retriever(responder) -> tuple[Retriever, _FakeDriver]:
    driver = _FakeDriver(responder)
    return Retriever(driver=driver, embedder=_ZeroEmbedder()), driver  # type: ignore[arg-type]


# -- pure helpers --


def test_glob_to_regex() -> None:
    assert _glob_to_regex("/api/orders/*") == r"/api/orders/.*"
    assert _glob_to_regex("*orders*") == r".*orders.*"
    assert _glob_to_regex("/api/orders/{id}") == r"/api/orders/\{id\}"
    assert _glob_to_regex("/x/?") == r"/x/."


def _edge(bean_id, name=None, stereotype=None, via=None) -> dict[str, Any]:
    return {"bean_id": bean_id, "name": name, "stereotype": stereotype, "via": via}


def test_bean_edges_drops_the_all_null_placeholder() -> None:
    rows = [_edge(None), _edge("com.acme.Repo", "repo", "Repository", "constructor")]
    edges = _bean_edges(rows)
    assert len(edges) == 1
    assert edges[0].bean_id == "com.acme.Repo"
    assert edges[0].via == "constructor"


# -- get_beans_for --


def test_get_beans_for_shapes_the_record() -> None:
    row = {
        "bean_id": "com.acme.OrderService",
        "name": "orderService",
        "stereotype": "Service",
        "scope": None,
        "primary": False,
        "bean_type": "com.acme.OrderService",
        "defined_in": None,
        "unresolved_injections": "[]",
        "injects": [
            _edge("com.acme.OrderRepo", "orderRepo", "Repository", "constructor"),
            _edge(None),
        ],
        "injected_by": [
            _edge("com.acme.OrderController", "orderController", "RestController", "constructor")
        ],
        "produces": [_edge(None)],
        "produced_by": [_edge(None)],
        "binds": ["orders.notify-on-create", "orders.max-lines-per-order"],
    }
    retriever, _driver = _retriever(lambda _cypher, _params: [row])

    detail = retriever.get_beans_for("com.acme.OrderService")

    assert detail is not None
    assert detail.stereotype == "Service"
    assert [e.name for e in detail.injects] == ["orderRepo"]
    assert [e.name for e in detail.injected_by] == ["orderController"]
    assert detail.produces == []
    assert detail.binds == ["orders.notify-on-create", "orders.max-lines-per-order"]


def test_get_beans_for_returns_none_when_no_bean() -> None:
    retriever, _driver = _retriever(lambda _cypher, _params: [])
    assert retriever.get_beans_for("com.acme.NotABean") is None


# -- get_endpoints --


def test_get_endpoints_passes_glob_regex_and_method() -> None:
    captured: dict[str, Any] = {}

    def responder(_cypher: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        captured.update(params)
        return [
            {
                "http_method": "GET",
                "path": "/api/orders/{id}",
                "framework": "spring-mvc",
                "produces": None,
                "consumes": None,
                "summary": "GET /api/orders/{id} -> OrderController.getOrder [spring-mvc]",
                "handler_qualified_name": "com.acme.OrderController.getOrder(Long)",
                "module": "orders-api",
            }
        ]

    retriever, _driver = _retriever(responder)
    results = retriever.get_endpoints(
        path_glob="/api/orders*", http_method="get", module="orders-api"
    )

    assert captured["path_regex"] == r"/api/orders.*"
    assert captured["http_method"] == "GET"
    assert captured["module"] == "orders-api"
    assert len(results) == 1
    assert results[0].handler_qualified_name == "com.acme.OrderController.getOrder(Long)"
    assert results[0].produces == []


def test_get_endpoints_no_filters_passes_nulls() -> None:
    captured: dict[str, Any] = {}

    def responder(_cypher: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        captured.update(params)
        return []

    retriever, _driver = _retriever(responder)
    retriever.get_endpoints()

    assert captured["path_regex"] is None
    assert captured["http_method"] is None
    assert captured["module"] is None


# -- search_code filters --


def test_search_code_threads_filters_into_the_query_params() -> None:
    seen: list[dict[str, Any]] = []

    def responder(_cypher: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        seen.append(params)
        return []

    retriever, _driver = _retriever(responder)
    retriever.search_code(
        "order service", stereotype="Service", annotation="Transactional", module="orders-api"
    )

    # both the vector and the full-text pass carry the filters
    assert seen, "no query ran"
    for params in seen:
        assert params["stereotype"] == "Service"
        assert params["annotation"] == "Transactional"
        assert params["module"] == "orders-api"


def test_search_code_without_filters_passes_nones() -> None:
    seen: list[dict[str, Any]] = []
    retriever, _driver = _retriever(lambda _c, params: seen.append(params) or [])
    retriever.search_code("anything")
    for params in seen:
        assert params["stereotype"] is None
        assert params["annotation"] is None
        assert params["module"] is None
