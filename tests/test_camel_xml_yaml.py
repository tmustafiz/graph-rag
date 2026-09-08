"""Apache Camel XML & YAML DSL + `@Consume` / `@Produce` annotations —
`CamelXmlParser`, `CamelYamlParser`, `CamelAnnotationExtractor` (via `JavaParser`).
"""

from pathlib import Path

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
