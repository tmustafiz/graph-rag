import json
from pathlib import Path

from graph_rag.graph.spring_xml_resolver import SpringXmlResolver
from graph_rag.ingest.parsers import SpringXmlParser

_CONTEXT = """\
<?xml version="1.0" encoding="UTF-8"?>
<beans xmlns="http://www.springframework.org/schema/beans"
       xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
       xmlns:context="http://www.springframework.org/schema/context"
       xmlns:p="http://www.springframework.org/schema/p">

    <context:component-scan base-package="com.acme.web, com.acme.core"/>
    <context:property-placeholder location="classpath:application.properties"/>
    <import resource="infra-context.xml"/>

    <bean id="orderService" class="com.acme.OrderServiceImpl" scope="singleton" primary="true">
        <constructor-arg ref="orderRepository"/>
        <property name="mailer" ref="mailer"/>
    </bean>

    <bean id="orderRepository" class="com.acme.JdbcOrderRepository">
        <property name="dataSource" ref="dataSource"/>
        <property name="url" value="${db.url}"/>
    </bean>

    <bean id="reportService" class="com.acme.ReportService" p:repo-ref="orderRepository"/>

    <bean name="legacyGateway,legacy" class="com.acme.LegacyGateway"/>

    <alias name="orderService" alias="orders"/>

    <bean id="listener" class="com.acme.Listener">
        <property name="handlers">
            <list>
                <ref bean="orderService"/>
                <bean class="com.acme.InlineHandler"/>
            </list>
        </property>
    </bean>
</beans>
"""

_NOT_SPRING = """<?xml version="1.0"?>
<configuration><appender name="X"/></configuration>
"""


def _parse(tmp_path: Path, name: str = "applicationContext.xml", body: str = _CONTEXT):
    path = tmp_path / name
    path.write_text(body)
    document = SpringXmlParser().parse(path)
    beans = {bean.bean_id: bean for bean in document.spring_xml_beans}
    return document, beans


def test_can_handle_only_beans_root(tmp_path: Path) -> None:
    beans_file = tmp_path / "applicationContext.xml"
    beans_file.write_text(_CONTEXT)
    other = tmp_path / "logback.xml"
    other.write_text(_NOT_SPRING)
    pom = tmp_path / "pom.xml"
    pom.write_text("<beans></beans>")

    assert SpringXmlParser.can_handle(beans_file) is True
    assert SpringXmlParser.can_handle(other) is False
    assert SpringXmlParser.can_handle(pom) is False


def test_bean_definitions_parsed(tmp_path: Path) -> None:
    _document, beans = _parse(tmp_path)

    order_service = beans["orderService"]
    assert order_service.class_name == "com.acme.OrderServiceImpl"
    assert order_service.scope == "singleton"
    assert order_service.primary is True
    assert beans["orderRepository"].primary is False


def _wiring(bean) -> list[tuple[str, str]]:
    return list(zip(bean.property_names, bean.property_refs, strict=True))


def test_constructor_and_property_ref_wiring(tmp_path: Path) -> None:
    _document, beans = _parse(tmp_path)

    assert beans["orderService"].constructor_arg_refs == ["orderRepository"]
    assert _wiring(beans["orderService"]) == [("mailer", "mailer")]
    # p:-namespace shortcut
    assert _wiring(beans["reportService"]) == [("repo", "orderRepository")]


def test_alias_and_multi_name_folded_into_bean(tmp_path: Path) -> None:
    _document, beans = _parse(tmp_path)

    assert "orders" in beans["orderService"].aliases
    # <bean name="legacyGateway,legacy"> → id is the first token, the rest are aliases
    assert "legacyGateway" in beans
    assert beans["legacyGateway"].aliases == ["legacy"]


def test_context_namespaces_captured_on_config_file(tmp_path: Path) -> None:
    document, _beans = _parse(tmp_path)
    config_file = document.config_files[0]

    assert config_file.format == "spring-xml"
    assert config_file.scan_packages == ["com.acme.web", "com.acme.core"]
    assert config_file.placeholder_locations == ["classpath:application.properties"]
    assert config_file.import_resources == ["infra-context.xml"]


def test_inner_bean_gets_generated_id_and_is_referenced(tmp_path: Path) -> None:
    _document, beans = _parse(tmp_path)

    inline_id = "InlineHandler#1"
    assert inline_id in beans
    assert beans[inline_id].class_name == "com.acme.InlineHandler"
    assert beans["listener"].property_refs == ["orderService", inline_id]


def test_value_placeholder_keys_captured(tmp_path: Path) -> None:
    _document, beans = _parse(tmp_path)

    assert beans["orderRepository"].value_placeholder_keys == ["db.url"]


_NESTED_PROFILE_CONTEXT = """\
<?xml version="1.0" encoding="UTF-8"?>
<beans xmlns="http://www.springframework.org/schema/beans">
    <bean id="baseDataSource" class="com.acme.BaseDataSource"/>
    <beans profile="dev">
        <bean id="devDataSource" class="org.h2.jdbcx.JdbcDataSource"/>
    </beans>
    <beans profile="prod">
        <bean id="prodDataSource" class="com.zaxxer.hikari.HikariDataSource"/>
    </beans>
</beans>
"""


def test_nested_profile_beans_are_parsed_and_tagged(tmp_path: Path) -> None:
    _document, beans = _parse(tmp_path, "datasource-context.xml", _NESTED_PROFILE_CONTEXT)

    assert set(beans) == {"baseDataSource", "devDataSource", "prodDataSource"}
    assert beans["baseDataSource"].profile is None
    assert beans["devDataSource"].profile == "dev"
    assert beans["prodDataSource"].profile == "prod"


# -- SpringXmlResolver._assemble (pure, no Neo4j) --


def _xml_def(**overrides):
    base = {
        "id": f"gid-{overrides.get('bean_id', 'x')}",
        "source_path": "/proj/src/main/resources/applicationContext.xml",
        "bean_id": "x",
        "bean_name": "x",
        "class_name": None,
        "scope": None,
        "primary": False,
        "abstract": False,
        "aliases": [],
        "constructor_arg_refs": [],
        "property_names": [],
        "property_refs": [],
        "value_placeholder_keys": [],
    }
    base.update(overrides)
    return base


def test_assemble_wires_refs_to_xml_and_annotation_beans() -> None:
    xml_defs = [
        _xml_def(
            id="gid-orderService",
            bean_id="orderService",
            bean_name="orderService",
            class_name="com.acme.OrderServiceImpl",
            constructor_arg_refs=["orderRepository"],
            property_names=["mailer"],
            property_refs=["mailer"],
        ),
        _xml_def(
            id="gid-orderRepository",
            bean_id="orderRepository",
            bean_name="orderRepository",
            class_name="com.acme.JdbcOrderRepository",
        ),
    ]
    # `mailer` is an annotation-wired @Service already in the graph.
    existing = [{"id": "com.acme.Mailer", "name": "mailer"}]

    assembled = SpringXmlResolver._assemble(xml_defs, existing, [], [])

    by_id = {row["id"]: row for row in assembled.bean_rows}
    assert by_id["gid-orderService"]["stereotype"] == "XmlBean"
    assert by_id["gid-orderService"]["bean_type"] == "com.acme.OrderServiceImpl"

    edges = {(edge["from"], edge["to"], edge["via"]) for edge in assembled.injects}
    assert ("gid-orderService", "gid-orderRepository", "xml-constructor") in edges
    assert ("gid-orderService", "com.acme.Mailer", "xml-property") in edges
    assert not assembled.stub_rows
    assert {row["class_name"] for row in assembled.is_bean_rows} == {
        "com.acme.OrderServiceImpl",
        "com.acme.JdbcOrderRepository",
    }


def test_assemble_unknown_ref_becomes_stub() -> None:
    xml_defs = [
        _xml_def(
            id="gid-a",
            bean_id="a",
            bean_name="a",
            property_names=["dep"],
            property_refs=["missingBean"],
        )
    ]

    assembled = SpringXmlResolver._assemble(xml_defs, [], [], [])

    assert assembled.stub_rows == [{"id": "xml-stub::missingBean", "name": "missingBean"}]
    assert {(edge["from"], edge["to"]) for edge in assembled.injects} == {
        ("gid-a", "xml-stub::missingBean")
    }


def test_assemble_ambiguous_ref_left_unresolved() -> None:
    xml_defs = [
        _xml_def(id="gid-x", bean_id="x", bean_name="x", constructor_arg_refs=["repo"]),
        _xml_def(id="gid-repo-a", bean_id="repo", bean_name="repo"),
    ]
    existing = [{"id": "ann-repo", "name": "repo"}]

    assembled = SpringXmlResolver._assemble(xml_defs, existing, [], [])

    assert not assembled.injects
    unresolved = json.loads(
        next(row for row in assembled.bean_rows if row["id"] == "gid-x")["unresolved_injections"]
    )
    assert unresolved and unresolved[0]["reason"].startswith("ambiguous:")


def test_assemble_value_placeholder_binds_config_property() -> None:
    xml_defs = [_xml_def(id="gid-r", bean_id="r", bean_name="r", value_placeholder_keys=["db.url"])]
    config_props = [{"id": "cp-url", "key": "db.url"}, {"id": "cp-other", "key": "db.user"}]

    assembled = SpringXmlResolver._assemble(xml_defs, [], [], config_props)

    assert assembled.binds == [{"from": "gid-r", "to": "cp-url"}]


def test_assemble_import_and_property_placeholder_become_imports_context() -> None:
    resources = "/proj/src/main/resources"
    config_files = [
        {
            "path": f"{resources}/applicationContext.xml",
            "format": "spring-xml",
            "import_resources": ["infra-context.xml"],
            "placeholder_locations": ["classpath:application.properties"],
        },
        {
            "path": f"{resources}/infra-context.xml",
            "format": "spring-xml",
            "import_resources": [],
            "placeholder_locations": [],
        },
        {"path": f"{resources}/application.properties", "format": "properties"},
    ]

    assembled = SpringXmlResolver._assemble([], [], config_files, [])

    assert {
        (pair["from"].split("/")[-1], pair["to"].split("/")[-1], pair["kind"])
        for pair in assembled.imports_context
    } == {
        ("applicationContext.xml", "infra-context.xml", "import"),
        ("applicationContext.xml", "application.properties", "property-placeholder"),
    }
