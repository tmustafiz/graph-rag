"""The `examples/enterprise-java` sample parses cleanly through the registry and
yields the v0.7.0 framework graph its README walkthrough documents (parse level
— no Neo4j).
"""

from pathlib import Path

from graph_rag.ingest.parser_registry import ParserRegistry

_EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "enterprise-java"


def _parse_all() -> dict[str, object]:
    registry = ParserRegistry()
    documents: dict[str, object] = {}
    for file in sorted(_EXAMPLE.rglob("*")):
        if not file.is_file():
            continue
        parser = registry.for_path(file)
        assert parser is not None, f"no parser for {file}"
        documents[file.name] = parser.parse(file)
    return documents


def test_every_example_file_parses() -> None:
    documents = _parse_all()
    assert {
        "OrderService.java",
        "OrderRouteBuilder.java",
        "camel-context.xml",
        "InventoryMapper.xml",
        "InventoryController.java",
    } <= set(documents)


def test_camel_routes_from_java_and_xml_pair_on_direct_enrich() -> None:
    documents = _parse_all()

    java_route = documents["OrderRouteBuilder.java"].camel_routes[0]
    assert java_route.route_id == "orders-enrich"
    assert java_route.from_uri == "direct:enrich"
    assert java_route.to_uris == ["jms:queue:orders-out"]
    assert java_route.steps[0] == {"index": 0, "kind": "bean", "ref": "OrderService.enrich"}

    xml_route = documents["camel-context.xml"].camel_routes[0]
    assert xml_route.route_id == "orders-xml-intake"
    assert "direct:enrich" in xml_route.to_uris  # → pairs with the Java route
    assert xml_route.on_exception == ["java.io.IOException"]
    assert [step["kind"] for step in xml_route.steps] == [
        "choice",
        "when",
        "to",
        "otherwise",
        "to",
        "end",
    ]


def test_event_and_kafka_flows() -> None:
    documents = _parse_all()

    published = documents["OrderService.java"].event_types[0]
    assert published.published_by == ["com.example.orders.OrderService.place(String,String)"]
    consumed = documents["OrderEventListener.java"].event_types[0]
    assert consumed.consumed_by == [
        "com.example.orders.OrderEventListener.onOrderPlaced(OrderPlacedEvent)"
    ]

    outbound = {d.name: d for d in documents["OrderService.java"].destinations}
    assert outbound["orders.outbound"].broker == "kafka"
    inbound = {d.name: d for d in documents["OrderEventListener.java"].destinations}
    assert inbound["orders.inbound"].consumed_by == [
        "com.example.orders.OrderEventListener.consume(String)"
    ]


def test_feign_client_and_target_controller_share_a_route() -> None:
    documents = _parse_all()

    client = documents["InventoryClient.java"].http_endpoints[0]
    assert client.outbound is True
    assert (client.http_method, client.path) == ("GET", "/inventory/items/{sku}")
    assert client.target_service == "inventory"

    controller = documents["InventoryController.java"].http_endpoints[0]
    assert controller.outbound is False
    assert (controller.http_method, controller.path) == ("GET", "/inventory/items/{sku}")


def test_aspect_and_transactional_and_mybatis() -> None:
    documents = _parse_all()

    advice = documents["AuditAspect.java"].aop_advice[0]
    assert advice.advice_kind == "around"
    assert advice.pointcut_expr == "execution(* com.example.orders.OrderService.*(..))"

    markers = {m.marker for m in documents["OrderService.java"].behavior_markers}
    assert "transactional" in markers

    statement = documents["InventoryMapper.xml"].sql_statements[0]
    assert statement.statement_id == "findBySku"
    assert statement.tables == [{"name": "inventory_items", "mode": "read"}]
    assert "i.sku, i.name, i.qty" in statement.text  # <include> expanded
