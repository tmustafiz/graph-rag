"""Apache Camel Java DSL routes: `JavaParser._collect_camel_routes` on a
`RouteBuilder`, plus `CamelResolver._assemble` (pure — no Neo4j).
"""

from pathlib import Path

from graph_rag.graph.camel_resolver import CamelResolver
from graph_rag.ingest.parsers.java_parser import JavaParser

_ROUTES = """\
package com.acme.routes;

import org.apache.camel.builder.RouteBuilder;

public class OrderRoutes extends RouteBuilder {

    @Override
    public void configure() throws Exception {
        onException(java.io.IOException.class, IllegalStateException.class)
            .handled(true)
            .to("log:errors");

        from("jms:queue:orders")
            .routeId("order-intake")
            .process("validateProcessor")
            .bean(OrderService.class, "enrich")
            .choice()
                .when(header("priority").isEqualTo("high"))
                    .to("direct:priority")
                .otherwise()
                    .to("direct:standard")
            .end()
            .to("bean:auditService?method=record");

        from("direct:priority")
            .routeId("priority-handler")
            .to("jms:queue:priority-out");
    }
}
"""


def _routes(tmp_path: Path):
    package_dir = tmp_path / "com" / "acme" / "routes"
    package_dir.mkdir(parents=True, exist_ok=True)
    path = package_dir / "OrderRoutes.java"
    path.write_text(_ROUTES)
    return {route.route_id: route for route in JavaParser().parse(path).camel_routes}


def test_from_to_and_route_id_are_extracted(tmp_path: Path) -> None:
    routes = _routes(tmp_path)

    intake = routes["order-intake"]
    assert intake.from_uri == "jms:queue:orders"
    assert "direct:priority" in intake.to_uris
    assert "direct:standard" in intake.to_uris
    assert "bean:auditService?method=record" in intake.to_uris


def test_process_and_bean_step_refs_are_captured(tmp_path: Path) -> None:
    routes = _routes(tmp_path)
    steps = routes["order-intake"].steps

    by_kind = {step["kind"]: step for step in steps}
    assert by_kind["process"]["ref"] == "validateProcessor"
    assert by_kind["bean"]["ref"] == "OrderService.enrich"
    # `.to("bean:auditService?method=record")` also yields an invoke ref
    to_bean = next(s for s in steps if s.get("uri", "").startswith("bean:"))
    assert to_bean["ref"] == "auditService.record"


def test_choice_when_otherwise_form_an_ordered_step_tree(tmp_path: Path) -> None:
    routes = _routes(tmp_path)
    kinds = [step["kind"] for step in routes["order-intake"].steps]

    assert kinds == [
        "process",
        "bean",
        "choice",
        "when",
        "to",
        "otherwise",
        "to",
        "end",
        "to",
    ]
    when = next(step for step in routes["order-intake"].steps if step["kind"] == "when")
    assert "priority" in when["predicate"]


def test_internal_endpoint_pairs_two_routes(tmp_path: Path) -> None:
    routes = _routes(tmp_path)

    assert "direct:priority" in routes["order-intake"].to_uris
    assert routes["priority-handler"].from_uri == "direct:priority"


def test_on_exception_types_are_captured_on_every_route(tmp_path: Path) -> None:
    routes = _routes(tmp_path)

    for route in routes.values():
        assert "java.io.IOException" in route.on_exception
        assert "IllegalStateException" in route.on_exception


# -- CamelResolver._assemble --


def _step(step_id, ref):
    return {"id": step_id, "ref": ref}


def _entity(qn, name, kind, owner=None):
    return {"qn": qn, "name": name, "kind": kind, "owner": owner}


def test_resolver_binds_type_dot_method_and_bare_type_and_bean() -> None:
    steps = [
        _step("s1", "OrderService.enrich"),
        _step("s2", "validateProcessor"),
        _step("s3", "auditService.record"),
    ]
    entities = [
        _entity("com.acme.OrderService", "OrderService", "class"),
        _entity(
            "com.acme.OrderService.enrich(Exchange)", "enrich", "method", "com.acme.OrderService"
        ),
        _entity("com.acme.AuditService", "AuditService", "class"),
        _entity(
            "com.acme.AuditService.record(Exchange)", "record", "method", "com.acme.AuditService"
        ),
    ]
    beans = [
        {"name": "validateProcessor", "qn": "com.acme.ValidateProcessor"},
        {"name": "auditService", "qn": "com.acme.AuditService"},
    ]

    assembled = CamelResolver._assemble(steps, entities, beans)

    assert {pair["step"]: pair["target"] for pair in assembled.invokes} == {
        "s1": "com.acme.OrderService.enrich(Exchange)",
        "s2": "com.acme.ValidateProcessor",
        "s3": "com.acme.AuditService.record(Exchange)",
    }


def test_resolver_leaves_ambiguous_and_unknown_refs_unbound() -> None:
    steps = [_step("s1", "Thing.run"), _step("s2", "nobody")]
    entities = [
        _entity("a.Thing.run()", "run", "method", "a.Thing"),
        _entity("b.Thing.run()", "run", "method", "b.Thing"),
    ]

    assembled = CamelResolver._assemble(steps, entities, [])

    assert assembled.invokes == []
