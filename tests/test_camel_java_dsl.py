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


def test_choice_branch_to_steps_are_conditional_with_their_predicate(tmp_path: Path) -> None:
    """#161 — a `to(...)` inside `choice()...end()` is conditional, not an
    unconditional route target."""
    routes = _routes(tmp_path)
    steps = routes["order-intake"].steps
    by_uri = {step["uri"]: step for step in steps if step.get("uri")}

    assert by_uri["direct:priority"]["conditional"] is True
    assert "priority" in by_uri["direct:priority"]["predicate"]
    assert by_uri["direct:standard"]["conditional"] is True
    assert by_uri["direct:standard"]["predicate"] == "otherwise"
    # the `.to("bean:auditService?method=record")` after `.end()` is main-path
    assert "conditional" not in by_uri["bean:auditService?method=record"]


_NESTED_BLOCK_IN_CHOICE = """\
package com.acme.routes;

import org.apache.camel.builder.RouteBuilder;

public class SplitRoutes extends RouteBuilder {

    @Override
    public void configure() throws Exception {
        from("jms:queue:orders")
            .routeId("split-in-choice")
            .choice()
                .when(header("priority").isEqualTo("high"))
                    .split(body())
                        .to("direct:each-item")
                    .end()
                    .to("direct:priority-done")
                .otherwise()
                    .to("direct:standard")
            .end()
            .to("log:audit");
    }
}
"""


def test_nested_end_inside_a_choice_branch_does_not_leak_conditional(tmp_path: Path) -> None:
    """#161 residual — a `.split(...).end()` inside a `when` branch closes the
    split, not the `choice`; the rest of the branch and the `otherwise` stay
    conditional, and only the post-`end()` step is an unconditional target."""
    package_dir = tmp_path / "com" / "acme" / "routes"
    package_dir.mkdir(parents=True, exist_ok=True)
    path = package_dir / "SplitRoutes.java"
    path.write_text(_NESTED_BLOCK_IN_CHOICE)

    route = next(
        r for r in JavaParser().parse(path).camel_routes if r.route_id == "split-in-choice"
    )
    by_uri = {step["uri"]: step for step in route.steps if step.get("uri")}

    assert by_uri["direct:each-item"]["conditional"] is True
    assert "priority" in by_uri["direct:each-item"]["predicate"]
    # the step after the nested `.end()` is still in the `when` branch
    assert by_uri["direct:priority-done"]["conditional"] is True
    assert "priority" in by_uri["direct:priority-done"]["predicate"]
    # the `otherwise` branch is not mislabeled unconditional either
    assert by_uri["direct:standard"]["conditional"] is True
    assert by_uri["direct:standard"]["predicate"] == "otherwise"
    # only the step after the `choice`'s own `.end()` is a real target
    assert "conditional" not in by_uri["log:audit"]


_ENDCHOICE_AND_ENDDOTRY = """\
package com.acme.routes;

import org.apache.camel.builder.RouteBuilder;

public class MixedEndRoutes extends RouteBuilder {

    @Override
    public void configure() throws Exception {
        from("jms:queue:a")
            .routeId("ends-with-endchoice")
            .choice()
                .when(header("vip").isEqualTo("yes"))
                    .to("direct:vip")
                .otherwise()
                    .to("direct:normal")
            .endChoice()
            .to("direct:after-a")
            .to("log:done-a");

        from("jms:queue:b")
            .routeId("dotry-in-branch")
            .choice()
                .when(header("vip").isEqualTo("yes"))
                    .doTry()
                        .to("direct:risky")
                    .doCatch(java.io.IOException.class)
                        .to("direct:recover")
                    .endDoTry()
                    .to("direct:after-try")
                .otherwise()
                    .to("direct:normal-b")
            .end()
            .to("direct:done-b");
    }
}
"""


def test_endchoice_closes_the_choice_and_following_steps_are_unconditional(tmp_path: Path) -> None:
    """#161 residual — `.endChoice()` closes the `choice`; `.to(...)` after it is
    a real (unconditional) target, not a dropped conditional one."""
    package_dir = tmp_path / "com" / "acme" / "routes"
    package_dir.mkdir(parents=True, exist_ok=True)
    path = package_dir / "MixedEndRoutes.java"
    path.write_text(_ENDCHOICE_AND_ENDDOTRY)

    routes = {route.route_id: route for route in JavaParser().parse(path).camel_routes}

    ends_with_endchoice = routes["ends-with-endchoice"]
    by_uri = {step["uri"]: step for step in ends_with_endchoice.steps if step.get("uri")}
    assert by_uri["direct:vip"]["conditional"] is True
    assert by_uri["direct:normal"]["conditional"] is True
    assert "conditional" not in by_uri["direct:after-a"]
    assert "conditional" not in by_uri["log:done-a"]
    assert "direct:after-a" in ends_with_endchoice.to_uris
    assert "log:done-a" in ends_with_endchoice.to_uris

    # `.endDoTry()` closes only the `doTry`; the rest of the `when` branch and the
    # `otherwise` stay conditional, and the step after the `choice`'s `.end()` is
    # a real target.
    dotry = routes["dotry-in-branch"]
    by_uri = {step["uri"]: step for step in dotry.steps if step.get("uri")}
    assert by_uri["direct:risky"]["conditional"] is True
    assert by_uri["direct:recover"]["conditional"] is True
    assert by_uri["direct:after-try"]["conditional"] is True
    assert by_uri["direct:normal-b"]["conditional"] is True
    assert "conditional" not in by_uri["direct:done-b"]
    assert "direct:done-b" in dotry.to_uris


_NESTED_ROUTE_BUILDER = """\
package com.acme.routes;

import org.apache.camel.builder.RouteBuilder;

public class RouteConfig {

    static class OrderRoutes extends RouteBuilder {
        @Override
        public void configure() {
            from("jms:orders").to("bean:orderService");
        }
    }
}
"""


def test_nested_static_inner_route_builder_is_walked(tmp_path: Path) -> None:
    """#159 — a `RouteBuilder` nested in a `@Configuration` class."""
    package_dir = tmp_path / "com" / "acme" / "routes"
    package_dir.mkdir(parents=True, exist_ok=True)
    path = package_dir / "RouteConfig.java"
    path.write_text(_NESTED_ROUTE_BUILDER)

    routes = JavaParser().parse(path).camel_routes
    assert [route.from_uri for route in routes] == ["jms:orders"]
    assert routes[0].to_uris == ["bean:orderService"]


def test_one_failing_framework_extractor_does_not_drop_the_file(
    tmp_path: Path, monkeypatch
) -> None:
    """#160 — a grammar edge case in one extractor must not lose CodeEntity data."""
    from graph_rag.ingest.parsers import java_parser

    def _boom(*_args, **_kwargs):
        raise RuntimeError("simulated grammar edge case")

    monkeypatch.setattr(java_parser.AopExtractor, "extract", _boom)
    package_dir = tmp_path / "com" / "acme" / "routes"
    package_dir.mkdir(parents=True, exist_ok=True)
    path = package_dir / "OrderRoutes.java"
    path.write_text(_ROUTES)

    document = JavaParser().parse(path)
    assert any(entity.kind == "class" for entity in document.code_entities)
    assert document.behavior_markers == []
    # other extractors still ran
    assert document.camel_routes


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
