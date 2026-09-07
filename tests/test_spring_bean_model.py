import json
from pathlib import Path

from graph_rag.graph.spring_bean_resolver import SpringBeanResolver
from graph_rag.ingest.models import ParsedDocument
from graph_rag.ingest.parsers import JavaParser

_TYPE_KINDS = {"class", "interface", "enum", "record", "annotation"}


def _rows(*sources: str, config_properties: list[tuple[str, str]] | None = None):
    """Turn parsed `.java` text into the graph-row shapes `_assemble` reads."""
    documents: list[ParsedDocument] = []
    for index, text in enumerate(sources):
        path = Path(f"/src/File{index}.java")
        documents.append(_parse(text, path))

    entities = [entity for document in documents for entity in document.code_entities]
    by_qn = {entity.qualified_name: entity for entity in entities}
    annotations = [ann for document in documents for ann in document.annotations]

    type_rows = [
        {
            "qn": entity.qualified_name,
            "name": entity.name,
            "kind": entity.kind,
            "annos": _annos_for(annotations, entity.qualified_name, "type"),
        }
        for entity in entities
        if entity.kind in _TYPE_KINDS
    ]

    member_owner_qns = {
        ann.owner_qualified_name
        for ann in annotations
        if ann.target in ("method", "constructor", "field")
    }
    member_rows = []
    for owner_qn in member_owner_qns:
        entity = by_qn.get(owner_qn)
        target = next(
            ann.target
            for ann in annotations
            if ann.owner_qualified_name == owner_qn
            and ann.target in ("method", "constructor", "field")
        )
        member_rows.append(
            {
                "qn": owner_qn,
                "name": entity.name if entity else owner_qn.rsplit(".", 1)[-1],
                "target": target,
                "signature": entity.signature if entity else None,
                "parent_qn": entity.parent_qualified_name if entity else None,
                "annos": _annos_for(annotations, owner_qn, target),
            }
        )

    ctor_by_type: dict[str, list[str]] = {}
    for entity in entities:
        if entity.kind == "constructor" and entity.parent_qualified_name:
            ctor_by_type.setdefault(entity.parent_qualified_name, []).append(entity.qualified_name)
    ctor_rows = [{"type_qn": qn, "ctor_qns": qns} for qn, qns in ctor_by_type.items()]

    hierarchy_rows = [
        {"sub": entity.qualified_name, "super": supertype}
        for entity in entities
        for supertype in (*entity.extends_types, *entity.implements_types)
    ]

    config_rows = [{"id": cp_id, "key": key} for cp_id, key in (config_properties or [])]
    return type_rows, member_rows, ctor_rows, hierarchy_rows, config_rows


def _parse(text: str, path: Path) -> ParsedDocument:
    tmp = Path(__file__).parent / "__spring_fixture__.java"
    tmp.write_text(text)
    try:
        document = JavaParser().parse(tmp)
    finally:
        tmp.unlink()
    return document.model_copy(
        update={
            "code_entities": [
                e.model_copy(update={"file_path": str(path)}) for e in document.code_entities
            ]
        }
    )


def _annos_for(annotations, owner_qn: str, target: str) -> list[dict]:
    return [
        {"name": ann.name, "fqn": ann.fqn, "attributes": json.dumps(ann.attributes)}
        for ann in annotations
        if ann.owner_qualified_name == owner_qn and ann.target == target
    ]


def _beans(assembled) -> dict[str, dict]:
    return {row["name"]: row for row in assembled.bean_rows}


def _injects(assembled) -> set[tuple[str, str, str]]:
    by_id = {row["id"]: row["name"] for row in assembled.bean_rows}
    return {(by_id[e["from"]], by_id[e["to"]], e["via"]) for e in assembled.injects}


def test_stereotypes_detected_including_restcontroller() -> None:
    assembled = SpringBeanResolver._assemble(
        *_rows(
            "package a; import org.springframework.stereotype.Service;\n"
            "@Service public class OrderService {}",
            "package a; import org.springframework.web.bind.annotation.RestController;\n"
            "@RestController public class OrderController {}",
            "package a; public class NotABean {}",
        )
    )

    beans = _beans(assembled)
    assert set(beans) == {"orderService", "orderController"}
    assert beans["orderService"]["stereotype"] == "Service"
    assert beans["orderController"]["stereotype"] == "RestController"


def test_constructor_injection_including_lombok_synthetic_ctor() -> None:
    plain = SpringBeanResolver._assemble(
        *_rows(
            "package a; import org.springframework.stereotype.Service;\n"
            "@Service public class A { private final B b; public A(B b) { this.b = b; } }",
            "package a; import org.springframework.stereotype.Service;\n@Service public class B {}",
        )
    )
    assert ("a", "b", "constructor") in _injects(plain)

    lombok = SpringBeanResolver._assemble(
        *_rows(
            "package a; import org.springframework.stereotype.Service;\n"
            "import lombok.RequiredArgsConstructor;\n"
            "@Service @RequiredArgsConstructor public class A { private final B b; }",
            "package a; import org.springframework.stereotype.Service;\n@Service public class B {}",
        )
    )
    assert ("a", "b", "constructor") in _injects(lombok)


def test_field_and_setter_injection() -> None:
    assembled = SpringBeanResolver._assemble(
        *_rows(
            "package a; import org.springframework.stereotype.Service;\n"
            "import org.springframework.beans.factory.annotation.Autowired;\n"
            "@Service public class A {\n"
            "  @Autowired private B b;\n"
            "  @Autowired public void setC(C c) {}\n"
            "}",
            "package a; import org.springframework.stereotype.Service;\n@Service public class B {}",
            "package a; import org.springframework.stereotype.Service;\n@Service public class C {}",
        )
    )

    assert ("a", "b", "field") in _injects(assembled)
    assert ("a", "c", "setter") in _injects(assembled)


def test_qualifier_disambiguates_two_implementations() -> None:
    sources = (
        "package a; public interface Repo {}",
        "package a; import org.springframework.stereotype.Repository;\n"
        '@Repository("jpaRepo") public class JpaRepo implements Repo {}',
        "package a; import org.springframework.stereotype.Repository;\n"
        '@Repository("jdbcRepo") public class JdbcRepo implements Repo {}',
        "package a; import org.springframework.stereotype.Service;\n"
        "import org.springframework.beans.factory.annotation.Autowired;\n"
        "import org.springframework.beans.factory.annotation.Qualifier;\n"
        "@Service public class Consumer {\n"
        '  @Autowired @Qualifier("jpaRepo") private Repo repo;\n'
        "}",
    )
    assembled = SpringBeanResolver._assemble(*_rows(*sources))
    assert ("consumer", "jpaRepo", "field") in _injects(assembled)

    # drop the @Qualifier line → ambiguous, left unresolved
    ambiguous = SpringBeanResolver._assemble(
        *_rows(
            *sources[:3], sources[3].replace('  @Autowired @Qualifier("jpaRepo")', "  @Autowired")
        )
    )
    consumer = _beans(ambiguous)["consumer"]
    unresolved = json.loads(consumer["unresolved_injections"])
    assert unresolved and unresolved[0]["reason"].startswith("ambiguous:")
    assert not _injects(ambiguous)


def test_bean_methods_become_beans_and_configuration_produces_them() -> None:
    assembled = SpringBeanResolver._assemble(
        *_rows(
            "package a; import org.springframework.context.annotation.Configuration;\n"
            "import org.springframework.context.annotation.Bean;\n"
            "@Configuration public class AppConfig {\n"
            "  @Bean public java.time.Clock clock() { return null; }\n"
            "}",
        )
    )

    beans = _beans(assembled)
    assert beans["clock"]["stereotype"] == "Bean"
    by_id = {row["id"]: row["name"] for row in assembled.bean_rows}
    assert {(by_id[p["from"]], by_id[p["to"]]) for p in assembled.produces} == {
        ("appConfig", "clock")
    }


def test_value_annotation_binds_to_config_property() -> None:
    assembled = SpringBeanResolver._assemble(
        *_rows(
            "package a; import org.springframework.stereotype.Service;\n"
            "import org.springframework.beans.factory.annotation.Value;\n"
            "@Service public class A {\n"
            '  @Value("${app.timeout:30}") private int timeout;\n'
            "}",
            config_properties=[("cp-timeout", "app.timeout"), ("cp-other", "app.name")],
        )
    )

    binds = {(row["from"], row["to"]) for row in assembled.binds}
    a_id = _beans(assembled)["a"]["id"]
    assert binds == {(a_id, "cp-timeout")}


def test_configuration_properties_binds_the_prefix_subtree() -> None:
    assembled = SpringBeanResolver._assemble(
        *_rows(
            "package a; "
            "import org.springframework.boot.context.properties.ConfigurationProperties;\n"
            "import org.springframework.stereotype.Component;\n"
            '@Component @ConfigurationProperties(prefix = "app.db") public class DbProps {}',
            config_properties=[
                ("cp-url", "app.db.url"),
                ("cp-pool", "app.db.pool.max"),
                ("cp-other", "app.name"),
            ],
        )
    )

    props_id = _beans(assembled)["dbProps"]["id"]
    assert {row["to"] for row in assembled.binds} == {"cp-url", "cp-pool"}
    assert all(row["from"] == props_id for row in assembled.binds)
