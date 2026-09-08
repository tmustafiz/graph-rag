"""v0.7.0 framework-aware retrieval — `get_routes`, `get_message_flows`,
`get_service_calls`, `get_architecture_outline`, the extended `get_beans_for`,
and the new `search_code` filters — driven by a fake Neo4j session (no live
Neo4j, matching `test_spring_mcp_tools.py`). Plus the centrality projection.
"""

from typing import Any

from graph_rag.graph.centrality_analyzer import _PROJECT_GRAPH
from graph_rag.mcp_server.retriever import Retriever


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


def _retriever(responder):
    driver = _FakeDriver(responder)
    return Retriever(driver=driver, embedder=_ZeroEmbedder())  # type: ignore[arg-type]


# -- get_routes --


def test_get_routes_shapes_steps_and_invokes_and_passes_the_uri_regex() -> None:
    captured: dict[str, Any] = {}

    def responder(_cypher: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        captured.update(params)
        return [
            {
                "route_id": "order-intake",
                "from_uri": "jms:queue:orders",
                "on_exception": ["java.io.IOException"],
                "to_uris": ["direct:priority", "bean:audit"],
                "invokes": ["com.acme.OrderService.enrich(Order)"],
                "raw_steps": [
                    {"i": 1, "k": "bean", "u": None},
                    {"i": 0, "k": "process", "u": None},
                    {"i": 2, "k": "to", "u": "direct:priority"},
                ],
                "module": "orders-camel",
                "source_path": "orders-camel/src/main/java/OrderRoutes.java",
            }
        ]

    routes = _retriever(responder).get_routes(uri_glob="*orders*", module="orders-camel")

    assert captured["uri_regex"] == r".*orders.*"
    assert captured["module"] == "orders-camel"
    route = routes[0]
    assert route.steps == ["process", "bean", "to(direct:priority)"]  # re-ordered by index
    assert route.invokes == ["com.acme.OrderService.enrich(Order)"]
    assert route.on_exception == ["java.io.IOException"]


# -- get_message_flows --


def test_get_message_flows_returns_one_result_per_matching_kind() -> None:
    def responder(_cypher: str, _params: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            {
                "kind": "event",
                "name": "com.acme.OrderPlacedEvent",
                "broker": None,
                "publishers": ["com.acme.OrderService.place(Order)"],
                "consumers": ["com.acme.Audit.on(OrderPlacedEvent)"],
            },
            {
                "kind": "destination",
                "name": "orders.outbound",
                "broker": "kafka",
                "publishers": [],
                "consumers": [],
            },
        ]

    flows = _retriever(responder).get_message_flows("OrderPlacedEvent")

    assert len(flows) == 1  # the empty destination row is dropped
    assert flows[0].kind == "event"
    assert flows[0].publishers == ["com.acme.OrderService.place(Order)"]
    assert flows[0].consumers == ["com.acme.Audit.on(OrderPlacedEvent)"]


# -- get_service_calls --


def test_get_service_calls_splits_inbound_and_outbound() -> None:
    def responder(_cypher: str, _params: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            {
                "inbound": [{"m": "GET", "p": "/orders/{id}"}],
                "outbound": [
                    {
                        "m": "GET",
                        "p": "/inventory/items/{sku}",
                        "svc": "inventory",
                        "th": "com.acme.inv.InventoryController.get(String)",
                    }
                ],
            }
        ]

    result = _retriever(responder).get_service_calls("com.acme.OrderService")

    by_direction = {edge.direction: edge for edge in result.endpoints}
    assert by_direction["inbound"].path == "/orders/{id}"
    assert by_direction["outbound"].target_service == "inventory"
    assert by_direction["outbound"].resolves_to_handler == (
        "com.acme.inv.InventoryController.get(String)"
    )


# -- get_architecture_outline --


def test_get_architecture_outline_groups_rows_by_module() -> None:
    def responder(_cypher: str, _params: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            {"module": "orders-api", "cat": "bean", "item": "orderService [Service]"},
            {"module": "orders-api", "cat": "endpoint", "item": "GET /orders/{id}"},
            {"module": "orders-camel", "cat": "route", "item": "intake: jms:queue:orders"},
            {"module": "orders-api", "cat": "scheduled", "item": "com.acme.Reaper.sweep()"},
        ]

    outline = _retriever(responder).get_architecture_outline()

    modules = {module.module: module for module in outline.modules}
    assert modules["orders-api"].beans == ["orderService [Service]"]
    assert modules["orders-api"].endpoints == ["GET /orders/{id}"]
    assert modules["orders-api"].scheduled_jobs == ["com.acme.Reaper.sweep()"]
    assert modules["orders-camel"].routes == ["intake: jms:queue:orders"]


# -- get_beans_for framework context --


def _bean_row(**overrides: Any) -> dict[str, Any]:
    base = {
        "bean_id": "com.acme.OrderService",
        "name": "orderService",
        "stereotype": "Service",
        "scope": None,
        "primary": False,
        "bean_type": "com.acme.OrderService",
        "defined_in": None,
        "unresolved_injections": "[]",
        "injects": [],
        "injected_by": [],
        "produces": [],
        "produced_by": [],
        "binds": [],
    }
    base.update(overrides)
    return base


def test_get_beans_for_adds_route_listener_and_behavior_context() -> None:
    def responder(cypher: str, _params: dict[str, Any]) -> list[dict[str, Any]]:
        if "behavior_lists" in cypher:
            return [
                {
                    "publishes": ["com.acme.OrderPlacedEvent"],
                    "listens_to": ["orders.inbound"],
                    "calls_services": ["GET /inventory/items/{sku} -> inventory"],
                    "invoked_by_routes": ["order-intake"],
                    "behavior_lists": [["transactional"], ["scheduled", "async"]],
                }
            ]
        return [_bean_row()]

    detail = _retriever(responder).get_beans_for("com.acme.OrderService")

    assert detail is not None
    assert detail.publishes == ["com.acme.OrderPlacedEvent"]
    assert detail.listens_to == ["orders.inbound"]
    assert detail.calls_services == ["GET /inventory/items/{sku} -> inventory"]
    assert detail.invoked_by_routes == ["order-intake"]
    assert detail.behaviors == ["async", "scheduled", "transactional"]  # sorted, deduped


# -- search_code framework filters --


def _is_index_pass(cypher: str) -> bool:
    return "db.index.vector" in cypher or "db.index.fulltext" in cypher


def test_search_code_prefilter_passes_the_new_framework_filter_params() -> None:
    prefilter_params: list[dict[str, Any]] = []

    def responder(cypher: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        if not _is_index_pass(cypher):
            prefilter_params.append(params)
            return [{"qualified_name": "com.acme.OrderService"}]
        return []

    _retriever(responder).search_code(
        "orders",
        route="order-intake",
        endpoint="/orders/*",
        listens_to="OrderPlacedEvent",
        behavior="transactional",
    )

    assert prefilter_params, "no graph pre-filter pass ran"
    params = prefilter_params[0]
    assert params["route"] == "order-intake"
    assert params["endpoint"] == r".*/orders/.*"  # glob → regex
    assert params["listens_to"] == "OrderPlacedEvent"
    assert params["behavior"] == "transactional"


def test_search_code_without_any_filter_still_skips_the_prefilter() -> None:
    calls: list[str] = []
    retriever = _retriever(lambda cypher, _p: calls.append(cypher) or [])
    retriever.search_code("anything")
    assert calls and all(_is_index_pass(cypher) for cypher in calls)


# -- centrality projection folds in framework edges --


def test_pagerank_projection_includes_framework_relationship_types() -> None:
    for relationship in ("INJECTS", "PUBLISHES", "CALLS_SERVICE", "INVOKES", "EXECUTES"):
        assert relationship in _PROJECT_GRAPH
    for label in ("Bean", "EventType", "HttpEndpoint", "CamelStep"):
        assert label in _PROJECT_GRAPH
