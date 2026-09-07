import builtins
import json
from pathlib import Path

import pytest

from graph_rag.ingest.parsers.java_parser import JavaParser


def _annotations_by_owner(document: object) -> dict[str, list]:
    grouped: dict[str, list] = {}
    for annotation in document.annotations:
        grouped.setdefault(annotation.owner_qualified_name, []).append(annotation)
    return grouped


def _write(tmp_path: Path, package: str, name: str, body: str) -> Path:
    package_dir = tmp_path.joinpath(*package.split("."))
    package_dir.mkdir(parents=True, exist_ok=True)
    path = package_dir / f"{name}.java"
    path.write_text(f"package {package};\n\n{body}\n")
    return path


def test_qualified_names_are_package_prefixed(tmp_path: Path) -> None:
    path = _write(tmp_path, "com.acme.orders", "OrderService", "public class OrderService {}")

    document = JavaParser().parse(path)

    entity = document.code_entities[0]
    assert entity.qualified_name == "com.acme.orders.OrderService"
    assert entity.kind == "class"
    assert entity.language == "java"
    assert entity.parent_qualified_name is None


def test_class_with_no_package_falls_back_to_bare_name(tmp_path: Path) -> None:
    path = tmp_path / "Bare.java"
    path.write_text("public class Bare { void tick() {} }\n")

    document = JavaParser().parse(path)

    by_name = {entity.qualified_name: entity for entity in document.code_entities}
    assert "Bare" in by_name
    assert "Bare.tick()" in by_name


def test_nested_types_and_members_form_contains_hierarchy(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "com.acme",
        "Outer",
        "public class Outer {\n"
        "    void top() {}\n"
        "    static class Inner {\n"
        "        interface Deep { void go(); }\n"
        "    }\n"
        "}",
    )

    document = JavaParser().parse(path)

    by_qualified_name = {entity.qualified_name: entity for entity in document.code_entities}
    assert by_qualified_name["com.acme.Outer.top()"].parent_qualified_name == "com.acme.Outer"
    assert by_qualified_name["com.acme.Outer.Inner"].parent_qualified_name == "com.acme.Outer"
    assert by_qualified_name["com.acme.Outer.Inner"].kind == "class"
    deep = by_qualified_name["com.acme.Outer.Inner.Deep"]
    assert deep.kind == "interface"
    assert deep.parent_qualified_name == "com.acme.Outer.Inner"
    assert by_qualified_name["com.acme.Outer.Inner.Deep.go()"].kind == "method"


def test_every_type_flavor_maps_to_its_kind(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "com.acme",
        "Flavors",
        "public class Flavors {\n"
        "    interface AnIface {}\n"
        "    enum AnEnum { A, B }\n"
        "    record ARecord(int a, int b) {}\n"
        "    @interface AnAnnotation {}\n"
        "}",
    )

    document = JavaParser().parse(path)

    kinds = {entity.name: entity.kind for entity in document.code_entities}
    assert kinds == {
        "Flavors": "class",
        "AnIface": "interface",
        "AnEnum": "enum",
        "ARecord": "record",
        "AnAnnotation": "annotation",
    }


def test_record_components_go_in_the_signature(tmp_path: Path) -> None:
    path = _write(tmp_path, "com.acme", "Pair", "public record Pair(int a, String b) {}")

    document = JavaParser().parse(path)

    record = next(entity for entity in document.code_entities if entity.kind == "record")
    assert record.signature == "(int a, String b)"


def test_overloads_are_disambiguated_by_parameter_types(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "com.acme",
        "Api",
        "public class Api {\n"
        "    void send(String message) {}\n"
        "    void send(String message, boolean urgent) {}\n"
        "    void send() {}\n"
        "}",
    )

    document = JavaParser().parse(path)

    method_qualified_names = {
        entity.qualified_name for entity in document.code_entities if entity.kind == "method"
    }
    assert method_qualified_names == {
        "com.acme.Api.send(String)",
        "com.acme.Api.send(String,boolean)",
        "com.acme.Api.send()",
    }


def test_constructor_is_its_own_entity(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "com.acme",
        "Widget",
        "public class Widget {\n    public Widget(int size) {}\n}",
    )

    document = JavaParser().parse(path)

    constructor = next(entity for entity in document.code_entities if entity.kind == "constructor")
    assert constructor.qualified_name == "com.acme.Widget.Widget(int)"
    assert constructor.parent_qualified_name == "com.acme.Widget"


def test_javadoc_becomes_docstring_and_embed_text(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "com.acme",
        "Doc",
        "public class Doc {\n    /**\n     * Does the thing.\n     */\n    void act() {}\n}",
    )

    document = JavaParser().parse(path)

    method = next(entity for entity in document.code_entities if entity.kind == "method")
    assert method.docstring == "Does the thing."
    assert method.embed_text == "Does the thing."


def test_synthesized_embed_text_when_no_javadoc(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "com.acme",
        "Plain",
        "public class Plain {\n    int size = 2;\n    int area() { return size * size; }\n}",
    )

    document = JavaParser().parse(path)

    type_entity = next(entity for entity in document.code_entities if entity.kind == "class")
    assert type_entity.docstring is None
    assert "Fields: size" in type_entity.embed_text
    assert "Methods: area" in type_entity.embed_text
    method = next(entity for entity in document.code_entities if entity.kind == "method")
    assert method.embed_text.startswith("method int area()")


def test_imports_are_collected_from_all_four_forms(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "com.acme.orders",
        "Consumer",
        "import com.acme.model.Order;\n"
        "import com.acme.util.*;\n"
        "import static com.acme.util.Log.info;\n"
        "import static com.acme.util.Math.*;\n\n"
        "public class Consumer {}",
    )

    document = JavaParser().parse(path)

    consumer = next(entity for entity in document.code_entities if entity.kind == "class")
    assert consumer.imports == [
        "com.acme.model.Order",
        "com.acme.util",
        "com.acme.util.Log.info",
        "com.acme.util.Math",
    ]


def test_file_imports_attach_only_to_the_first_top_level_type(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "com.acme",
        "Primary",
        "import com.acme.model.Order;\n\npublic class Primary {}\n\nclass Helper {}",
    )

    document = JavaParser().parse(path)

    by_name = {entity.name: entity for entity in document.code_entities}
    assert by_name["Primary"].imports == ["com.acme.model.Order"]
    assert by_name["Helper"].imports == []


def test_calls_resolve_for_the_four_static_shapes(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "com.acme.orders",
        "Caller",
        "import com.acme.model.Order;\n"
        "import static com.acme.util.Log.info;\n\n"
        # helper() unqualified, this.reset(), statically-imported info(),
        # Order.parse() on an imported type, and getThing().run() (skipped).
        "public class Caller {\n"
        "    void drive() {\n"
        "        helper();\n"
        "        this.reset();\n"
        '        info("hi");\n'
        '        Order.parse("x");\n'
        "        getThing().run();\n"
        "    }\n"
        "    void helper() {}\n"
        "    void reset() {}\n"
        "}",
    )

    document = JavaParser().parse(path)

    drive = next(
        entity for entity in document.code_entities if entity.qualified_name.endswith("drive()")
    )
    assert set(drive.calls) == {
        "com.acme.orders.Caller.helper()",
        "com.acme.orders.Caller.reset()",
        "com.acme.util.Log.info",
        "com.acme.model.Order.parse",
    }


def test_ambiguous_overload_call_is_skipped_rather_than_guessed(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "com.acme",
        "Ambig",
        "public class Ambig {\n"
        "    void run() { work(1); }\n"
        "    void work(int a) {}\n"
        "    void work(String a) {}\n"
        "}",
    )

    document = JavaParser().parse(path)

    run = next(entity for entity in document.code_entities if entity.name == "run")
    assert run.calls == []


def test_syntax_error_yields_a_partial_result_without_raising(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "com.acme",
        "Broken",
        "public class Broken {\n    void ok() {}\n    void busted( {\n}",
    )

    document = JavaParser().parse(path)

    names = {entity.name for entity in document.code_entities}
    assert "Broken" in names
    assert "ok" in names


def test_can_handle_only_matches_java_files() -> None:
    assert JavaParser.can_handle(Path("Foo.java")) is True
    assert JavaParser.can_handle(Path("Foo.JAVA")) is True
    assert JavaParser.can_handle(Path("Foo.py")) is False


def test_type_level_annotations_are_captured_with_resolved_fqn(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "com.acme.web",
        "OrderController",
        "import org.springframework.web.bind.annotation.RestController;\n"
        "import org.springframework.web.bind.annotation.RequestMapping;\n\n"
        "@RestController\n"
        '@RequestMapping(path = "/orders", produces = {"application/json", "text/plain"})\n'
        "public class OrderController {}",
    )

    document = JavaParser().parse(path)

    annotations = _annotations_by_owner(document)["com.acme.web.OrderController"]
    by_name = {annotation.name: annotation for annotation in annotations}
    assert all(annotation.target == "type" for annotation in annotations)
    assert by_name["RestController"].fqn == (
        "org.springframework.web.bind.annotation.RestController"
    )
    assert by_name["RestController"].attributes == {}
    request_mapping = by_name["RequestMapping"]
    assert request_mapping.attributes == {
        "path": "/orders",
        "produces": ["application/json", "text/plain"],
    }
    # `attributes_json` is what the graph writer persists (Neo4j has no nested maps).
    assert json.loads(request_mapping.attributes_json)["path"] == "/orders"


def test_unresolved_annotation_falls_back_to_simple_name(tmp_path: Path) -> None:
    path = _write(tmp_path, "com.acme", "Legacy", "@Deprecated\npublic class Legacy {}")

    annotation = _annotations_by_owner(JavaParser().parse(path))["com.acme.Legacy"][0]
    assert annotation.name == "Deprecated"
    assert annotation.fqn == "Deprecated"


def test_annotated_fields_become_field_entities_plain_fields_do_not(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "com.acme",
        "OrderService",
        "import org.springframework.beans.factory.annotation.Autowired;\n"
        "import org.springframework.beans.factory.annotation.Value;\n\n"
        "public class OrderService {\n"
        "    @Autowired private OrderRepo repo;\n"
        '    @Value("${app.timeout:30}") private int timeout;\n'
        "    private int callCount;\n"
        "}",
    )

    document = JavaParser().parse(path)

    by_qn = {entity.qualified_name: entity for entity in document.code_entities}
    assert by_qn["com.acme.OrderService#repo"].kind == "field"
    assert by_qn["com.acme.OrderService#repo"].parent_qualified_name == "com.acme.OrderService"
    assert "com.acme.OrderService#timeout" in by_qn
    assert "com.acme.OrderService#callCount" not in by_qn  # plain field: no entity
    # plain field still folded into the owning type's embed_text
    assert "callCount" in by_qn["com.acme.OrderService"].embed_text

    value = _annotations_by_owner(document)["com.acme.OrderService#timeout"][0]
    assert value.target == "field"
    assert value.name == "Value"
    assert value.attributes == {"value": "${app.timeout:30}"}


def test_method_and_parameter_annotations(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "com.acme.web",
        "OrderApi",
        "import org.springframework.web.bind.annotation.GetMapping;\n"
        "import org.springframework.web.bind.annotation.PathVariable;\n\n"
        "public class OrderApi {\n"
        '    @GetMapping("/{id}")\n'
        "    Order get(@PathVariable Long id, int page) { return null; }\n"
        "}",
    )

    document = JavaParser().parse(path)

    annotations = _annotations_by_owner(document)["com.acme.web.OrderApi.get(Long,int)"]
    by_name = {annotation.name: annotation for annotation in annotations}
    assert by_name["GetMapping"].target == "method"
    assert by_name["GetMapping"].attributes == {"value": "/{id}"}
    assert by_name["PathVariable"].target == "param:id"
    assert by_name["PathVariable"].fqn == "org.springframework.web.bind.annotation.PathVariable"


def test_annotation_attribute_value_types(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "com.acme",
        "Widget",
        "public class Widget {\n"
        '    @Column(name = "id", nullable = false, length = 36, ratio = 1.5)\n'
        "    private String id;\n"
        "    @WithClass(value = Widget.class)\n"
        "    void a() {}\n"
        "    @Outer(inner = @Inner(x = 1))\n"
        "    void b() {}\n"
        "}",
    )

    document = JavaParser().parse(path)
    by_owner = _annotations_by_owner(document)

    column = by_owner["com.acme.Widget#id"][0]
    assert column.attributes == {"name": "id", "nullable": False, "length": 36, "ratio": 1.5}
    assert by_owner["com.acme.Widget.a()"][0].attributes == {"value": "Widget.class"}
    assert by_owner["com.acme.Widget.b()"][0].attributes == {"inner": {"@Inner": {"x": 1}}}


def test_graph_writer_annotation_rows_shape(tmp_path: Path) -> None:
    from graph_rag.graph.graph_writer import GraphWriter

    path = _write(
        tmp_path,
        "com.acme",
        "Thing",
        "@Deprecated\npublic class Thing {}",
    )
    document = JavaParser().parse(path)

    rows = GraphWriter._annotation_rows(document)
    assert rows == [
        {
            "id": document.annotations[0].id,
            "owner_qualified_name": "com.acme.Thing",
            "target": "type",
            "fqn": "Deprecated",
            "name": "Deprecated",
            "attributes_json": "{}",
            "line": document.annotations[0].line,
        }
    ]


def _by_qn(document: object) -> dict[str, object]:
    return {entity.qualified_name: entity for entity in document.code_entities}


def test_lombok_data_synthesizes_getters_and_setters(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "com.acme",
        "Customer",
        "import lombok.Data;\n\n"
        "@Data\n"
        "public class Customer {\n"
        "    private Long id;\n"
        "    private String name;\n"
        "    private boolean active;\n"
        "}",
    )

    by_qn = _by_qn(JavaParser().parse(path))

    getter = by_qn["com.acme.Customer.getId()"]
    assert getter.kind == "method"
    assert getter.synthetic is True
    assert getter.origin == "lombok"
    assert by_qn["com.acme.Customer.setId(Long)"].synthetic is True
    assert "com.acme.Customer.isActive()" in by_qn  # boolean → isX
    assert "com.acme.Customer.setName(String)" in by_qn


def test_lombok_requiredargsconstructor_uses_final_fields(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "com.acme",
        "OrderService",
        "import lombok.RequiredArgsConstructor;\n\n"
        "@RequiredArgsConstructor\n"
        "public class OrderService {\n"
        "    private final OrderRepository repo;\n"
        "    private final Clock clock;\n"
        "    private int cacheSize = 100;\n"
        "}",
    )

    by_qn = _by_qn(JavaParser().parse(path))

    constructor = by_qn["com.acme.OrderService.OrderService(OrderRepository,Clock)"]
    assert constructor.kind == "constructor"
    assert constructor.synthetic is True
    assert constructor.origin == "lombok"
    # the initialised, non-final field is not a constructor parameter
    assert "com.acme.OrderService.OrderService(OrderRepository,Clock,int)" not in by_qn


def test_lombok_slf4j_synthesizes_a_log_field(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "com.acme",
        "Worker",
        "import lombok.extern.slf4j.Slf4j;\n\n@Slf4j\npublic class Worker {\n}",
    )

    log = _by_qn(JavaParser().parse(path))["com.acme.Worker#log"]
    assert log.kind == "field"
    assert log.name == "log"
    assert (log.synthetic, log.origin) == (True, "lombok")


def test_lombok_value_is_immutable_no_setters_and_builder(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "com.acme",
        "Money",
        "import lombok.Value;\nimport lombok.Builder;\n\n"
        "@Value\n@Builder\npublic class Money {\n"
        "    String currency;\n"
        "    long amount;\n"
        "}",
    )

    by_qn = _by_qn(JavaParser().parse(path))

    assert "com.acme.Money.getCurrency()" in by_qn
    assert not any(qn.startswith("com.acme.Money.set") for qn in by_qn)
    assert by_qn["com.acme.Money.MoneyBuilder"].kind == "class"
    assert by_qn["com.acme.Money.builder()"].synthetic is True
    # @Value implies an all-args constructor
    assert "com.acme.Money.Money(String,long)" in by_qn


def test_explicit_accessor_is_not_duplicated_by_lombok(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "com.acme",
        "Account",
        "import lombok.Data;\n\n@Data\npublic class Account {\n"
        "    private String owner;\n"
        "    public String getOwner() { return owner; }\n"
        "}",
    )

    owners = [e for e in JavaParser().parse(path).code_entities if e.name == "getOwner"]
    assert len(owners) == 1
    assert owners[0].synthetic is False


def test_non_lombok_class_has_no_synthetic_entities(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "com.acme",
        "Plain",
        "public class Plain {\n    private int count;\n}",
    )

    assert all(not e.synthetic for e in JavaParser().parse(path).code_entities)


def test_parse_without_tree_sitter_raises_actionable_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_import = builtins.__import__

    def fake_import(name: str, *args: object, **kwargs: object):  # noqa: ANN202
        if name == "tree_sitter_language_pack":
            raise ModuleNotFoundError("No module named 'tree_sitter_language_pack'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    with pytest.raises(RuntimeError, match=r"'java' extra"):
        JavaParser().parse(Path("Whatever.java"))
