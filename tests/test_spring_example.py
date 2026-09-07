"""The `examples/spring-boot` sample parses cleanly and yields the Java-
framework graph the walkthrough documents (parse level — no Neo4j).
"""

from pathlib import Path

from graph_rag.ingest.parser_registry import ParserRegistry

_EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "spring-boot"


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
    # parent + 2 module poms, the .java files, application.yml, legacy-context.xml, README
    assert "pom.xml" in documents
    assert {"OrderController.java", "OrderService.java", "OrderRepository.java"} <= set(documents)


def test_controller_endpoints_extracted() -> None:
    document = _parse_all()["OrderController.java"]
    routes = {(e.http_method, e.path) for e in document.http_endpoints}
    assert routes == {
        ("GET", "/api/orders/{id}"),
        ("GET", "/api/orders"),
        ("POST", "/api/orders"),
    }
    assert all(e.framework == "spring-mvc" for e in document.http_endpoints)


def test_repository_and_entities_extracted() -> None:
    documents = _parse_all()

    repo = documents["OrderRepository.java"].spring_data_repositories[0]
    assert (repo.entity_type, repo.id_type, repo.base) == ("Order", "Long", "JpaRepository")
    kinds = dict(zip(repo.method_names, repo.method_query_kinds, strict=True))
    assert kinds["findByCustomerIdAndStatusOrderByCreatedAtDesc"] == "derived"
    assert kinds["withAtLeastLines"] == "jpql"
    assert kinds["updateStatus"] == "modifying"

    order = documents["Order.java"].jpa_entities[0]
    assert order.table == "orders"
    assert order.id_fields == ["id"]

    line = documents["OrderLine.java"].jpa_entities[0]
    assert list(zip(line.association_kinds, line.association_targets, strict=True)) == [
        ("many-to-one", "Order")
    ]


def test_xml_bean_and_config_extracted() -> None:
    documents = _parse_all()

    bean = documents["legacy-context.xml"].spring_xml_beans[0]
    assert bean.bean_id == "notificationGateway"
    assert bean.class_name == "com.example.orders.api.EmailNotificationGateway"
    assert bean.value_placeholder_keys == ["notification.from-address"]

    config_file = documents["legacy-context.xml"].config_files[0]
    assert config_file.format == "spring-xml"
    assert config_file.placeholder_locations == ["classpath:application.yml"]

    property_keys = {p.key for p in documents["application.yml"].config_properties}
    assert "orders.notify-on-create" in property_keys
    assert "spring.datasource.url" in property_keys


def test_service_is_a_stereotype_with_injection_points() -> None:
    document = _parse_all()["OrderService.java"]
    service = next(e for e in document.code_entities if e.name == "OrderService")
    service_annotations = {
        a.name for a in document.annotations if a.owner_qualified_name == service.qualified_name
    }
    assert "Service" in service_annotations
    # constructor + the @Autowired field are both present as members
    member_kinds = {e.kind for e in document.code_entities if e.parent_qualified_name}
    assert {"constructor", "field", "method"} <= member_kinds
