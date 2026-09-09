"""Apache Camel XML & YAML DSL + `@Consume` / `@Produce` annotations —
`CamelXmlParser`, `CamelYamlParser`, `CamelAnnotationExtractor` (via `JavaParser`).
"""

from pathlib import Path

from graph_rag.ingest.parser_registry import ParserRegistry
from graph_rag.ingest.parsers.camel_xml_parser import CamelXmlParser
from graph_rag.ingest.parsers.camel_yaml_parser import CamelYamlParser
from graph_rag.ingest.parsers.java_parser import JavaParser

_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<camelContext xmlns="http://camel.apache.org/schema/spring">
    <onException>
        <exception>java.io.IOException</exception>
        <handled><constant>true</constant></handled>
    </onException>
    <route id="xml-intake">
        <from uri="jms:queue:in"/>
        <choice>
            <when>
                <simple>${header.priority} == 'high'</simple>
                <to uri="direct:shared"/>
            </when>
            <otherwise>
                <to uri="direct:standard"/>
            </otherwise>
        </choice>
        <bean ref="auditService" method="record"/>
    </route>
</camelContext>
"""

_YAML = """\
- route:
    id: yaml-handler
    from:
      uri: "direct:shared"
      steps:
        - to:
            uri: "log:handled"
        - to: "jms:queue:out"
"""

_CONSUMER = """\
package com.acme.camel;

import org.apache.camel.Consume;
import org.apache.camel.Produce;

public class MailPojo {

    @Produce(uri = "direct:shared")
    private Object producer;

    @Consume(uri = "jms:queue:in")
    public void onMessage(String body) {}
}
"""


def test_xml_route_with_choice_when(tmp_path: Path) -> None:
    path = tmp_path / "routes.xml"
    path.write_text(_XML)
    assert CamelXmlParser.can_handle(path) is True

    routes = CamelXmlParser().parse(path).camel_routes
    assert len(routes) == 1
    route = routes[0]
    assert route.route_id == "xml-intake"
    assert route.from_uri == "jms:queue:in"
    assert route.on_exception == ["java.io.IOException"]

    kinds = [step["kind"] for step in route.steps]
    assert kinds == ["choice", "when", "to", "otherwise", "to", "end", "bean"]
    when = next(step for step in route.steps if step["kind"] == "when")
    assert "priority" in when["predicate"]
    assert next(s for s in route.steps if s["kind"] == "bean")["ref"] == "auditService.record"

    # #161 — branch `to` steps are conditional, the trailing bean step is not
    by_uri = {step["uri"]: step for step in route.steps if step.get("uri")}
    assert by_uri["direct:shared"]["conditional"] is True
    assert "priority" in by_uri["direct:shared"]["predicate"]
    assert by_uri["direct:standard"]["predicate"] == "otherwise"
    assert route.to_uris == ["direct:shared", "direct:standard"]


def test_yaml_route(tmp_path: Path) -> None:
    path = tmp_path / "camel-routes.yaml"
    path.write_text(_YAML)
    assert CamelYamlParser.can_handle(path) is True

    routes = CamelYamlParser().parse(path).camel_routes
    assert len(routes) == 1
    route = routes[0]
    assert route.route_id == "yaml-handler"
    assert route.from_uri == "direct:shared"
    assert route.to_uris == ["log:handled", "jms:queue:out"]


_GENERIC_ROUTE_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<gateway xmlns="urn:acme:gateway">
    <route id="north" path="/north"/>
    <route id="south" path="/south"/>
</gateway>
"""

_NOTIFICATION_YAML = "from: no-reply@example.com\nsubject: Welcome\n"


def test_generic_xml_with_a_route_element_is_not_claimed_as_camel(tmp_path: Path) -> None:
    """#162 — dispatch on the root tag + Camel namespace, not any `<route>`."""
    path = tmp_path / "gateway.xml"
    path.write_text(_GENERIC_ROUTE_XML)

    assert CamelXmlParser.can_handle(path) is False
    assert not isinstance(ParserRegistry().for_path(path), CamelXmlParser)


def test_yaml_with_a_lone_from_key_is_not_claimed_as_camel(tmp_path: Path) -> None:
    """#162 — a `notification.yml` with `from: <address>` is config, not a route."""
    path = tmp_path / "notification.yml"
    path.write_text(_NOTIFICATION_YAML)

    assert CamelYamlParser.can_handle(path) is False
    assert not isinstance(ParserRegistry().for_path(path), CamelYamlParser)


_BLUEPRINT_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<blueprint xmlns="http://www.osgi.org/xmlns/blueprint/v1.0.0">
    <camelContext xmlns="http://camel.apache.org/schema/blueprint">
        <route id="bp-intake">
            <from uri="jms:queue:in"/>
            <to uri="log:done"/>
        </route>
    </camelContext>
</blueprint>
"""


def test_osgi_blueprint_wrapping_a_camel_context_is_parsed(tmp_path: Path) -> None:
    """#162 residual — a `<blueprint>` root that embeds a `<camelContext>` is a
    common Karaf / ServiceMix deployment; its routes must still be extracted."""
    path = tmp_path / "blueprint.xml"
    path.write_text(_BLUEPRINT_XML)

    assert CamelXmlParser.can_handle(path) is True
    routes = CamelXmlParser().parse(path).camel_routes
    assert [route.route_id for route in routes] == ["bp-intake"]
    assert routes[0].from_uri == "jms:queue:in"
    assert routes[0].to_uris == ["log:done"]


_UNKNOWN_WRAPPER_BARE_CAMELCONTEXT = """\
<?xml version="1.0" encoding="UTF-8"?>
<application xmlns="urn:acme:app-descriptor">
    <docs>
        <camelContext>
            <route id="example-only">
                <from uri="jms:queue:in"/>
            </route>
        </camelContext>
    </docs>
</application>
"""


def test_unknown_wrapper_with_a_bare_camel_context_is_not_claimed(tmp_path: Path) -> None:
    """#162 round 3 — under an unknown (non-Camel, non-`<beans>`) root, only a
    *namespaced* `<camelContext>` counts; a bare element that merely shares the
    local name (a doc snippet / custom schema) must fall through to the generic
    parsers."""
    path = tmp_path / "app-descriptor.xml"
    path.write_text(_UNKNOWN_WRAPPER_BARE_CAMELCONTEXT)

    assert CamelXmlParser.can_handle(path) is False
    assert not isinstance(ParserRegistry().for_path(path), CamelXmlParser)


def test_consume_annotation_becomes_a_route(tmp_path: Path) -> None:
    package_dir = tmp_path / "com" / "acme" / "camel"
    package_dir.mkdir(parents=True, exist_ok=True)
    path = package_dir / "MailPojo.java"
    path.write_text(_CONSUMER)

    document = JavaParser().parse(path)
    consume = next(r for r in document.camel_routes if r.route_id == "onMessage@Consume")
    assert consume.from_uri == "jms:queue:in"
    assert consume.steps == [{"index": 0, "kind": "bean", "ref": "MailPojo.onMessage"}]

    assert document.camel_produce_endpoints == [
        {"uri": "direct:shared", "producer_qn": "com.acme.camel.MailPojo"}
    ]


def test_endpoints_pair_across_all_three_dsls(tmp_path: Path) -> None:
    xml_path = tmp_path / "routes.xml"
    xml_path.write_text(_XML)
    yaml_path = tmp_path / "camel-routes.yaml"
    yaml_path.write_text(_YAML)
    java_dir = tmp_path / "com" / "acme" / "camel"
    java_dir.mkdir(parents=True, exist_ok=True)
    java_path = java_dir / "MailPojo.java"
    java_path.write_text(_CONSUMER)

    produced_to: set[str] = set()
    consumed_from: set[str] = set()
    for document in (
        CamelXmlParser().parse(xml_path),
        CamelYamlParser().parse(yaml_path),
        JavaParser().parse(java_path),
    ):
        for route in document.camel_routes:
            consumed_from.add(route.from_uri)
            produced_to.update(route.to_uris)
        produced_to.update(e["uri"] for e in document.camel_produce_endpoints)

    # `direct:shared` is a TO in the XML route + a @Produce endpoint, and a FROM
    # in the YAML route — the shared-node MERGE pairs them in the graph.
    assert "direct:shared" in produced_to
    assert "direct:shared" in consumed_from
