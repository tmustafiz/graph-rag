import hashlib
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..models import Annotation, CodeEntity, ParsedDocument, Source
from .http_endpoint_extractor import HttpEndpointExtractor
from .lombok_synthesizer import LombokSynthesizer
from .spring_data_extractor import REACTIVE_BASES, SPRING_DATA_BASES, SpringDataExtractor

if TYPE_CHECKING:
    from tree_sitter import Node

_WHITESPACE_RE = re.compile(r"\s+")

_ANNOTATION_NODE_TYPES = ("marker_annotation", "annotation")
_INTEGER_LITERALS = (
    "decimal_integer_literal",
    "hex_integer_literal",
    "octal_integer_literal",
    "binary_integer_literal",
)
_FLOAT_LITERALS = ("decimal_floating_point_literal", "hex_floating_point_literal")

# Java type-declaration node types → the `CodeEntity.kind` we emit for each.
_TYPE_KINDS: dict[str, str] = {
    "class_declaration": "class",
    "interface_declaration": "interface",
    "enum_declaration": "enum",
    "record_declaration": "record",
    "annotation_type_declaration": "annotation",
}
_MEMBER_KINDS: dict[str, str] = {
    "method_declaration": "method",
    "constructor_declaration": "constructor",
}


class JavaParser:
    """Parses a `.java` file into a `Source` + `CodeEntity` list via tree-sitter.

    Types (class / interface / enum / record / `@interface`) and their
    methods / constructors become `CodeEntity` nodes. Plain fields are folded
    into the owning type's `embed_text` rather than emitted as entities (they
    are never `CALLS`/`IMPORTS` endpoints), but a field carrying at least one
    annotation *is* emitted as a `field` entity (`qualified_name` =
    ``<type>#<field>``) so framework wiring like `@Autowired` / `@Value` /
    `@Column` is visible. There is no file-level `module` entity — Java has no
    first-class unit below the package — so the file's imports are attached to
    its first top-level type.

    Annotations on types, methods, constructors, fields, and parameters are
    captured as `Annotation` records on `ParsedDocument.annotations`, each
    keyed to its owner entity's `qualified_name`; parameter annotations use a
    ``param:<name>`` target since parameters are not their own entities.

    `qualified_name` is the fully-qualified, overload-safe name
    (`com.acme.orders.OrderService.submit(Order,boolean)`); parameter types are
    taken verbatim from the source since there is no type resolution.
    `calls`/`imports` are best-effort static only, resolved just for the shapes
    that need no type inference — everything else is skipped rather than
    guessed, matching `PythonParser`.
    """

    @staticmethod
    def can_handle(path: Path) -> bool:
        return path.suffix.lower() == ".java"

    def parse(self, path: Path) -> ParsedDocument:
        try:
            from tree_sitter_language_pack import get_parser
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "Parsing Java needs the optional 'java' extra. Install it with "
                "`pip install 'grag-mcp[java]'` (or `uv sync --extra java`)."
            ) from exc

        content = path.read_bytes()
        source = Source(
            path=str(path),
            source_type="java",
            content_hash=hashlib.sha256(content).hexdigest(),
            ingested_at=datetime.now(UTC),
        )

        tree = get_parser("java").parse(content)
        root = tree.root_node

        package = self._package_name(root, content)
        imports, static_aliases, imported_types = self._collect_imports(root, content)

        type_nodes = [child for child in root.children if child.type in _TYPE_KINDS]
        same_file_types = self._same_file_type_names(type_nodes, package, content)

        entities: list[CodeEntity] = []
        annotations: list[Annotation] = []
        for index, type_node in enumerate(type_nodes):
            entities.extend(
                self._build_type_entities(
                    type_node,
                    content,
                    path=path,
                    parent_qualified_name=None,
                    package_prefix=package,
                    file_imports=imports if index == 0 else [],
                    static_aliases=static_aliases,
                    imported_types=imported_types,
                    same_file_types=same_file_types,
                    annotations=annotations,
                )
            )

        repo_bindings = self._collect_repo_bindings(
            type_nodes, content, package, imported_types, same_file_types
        )
        jpa_entities, spring_data_repositories = SpringDataExtractor.extract(
            entities, annotations, repo_bindings
        )

        return ParsedDocument(
            source=source,
            code_entities=entities,
            annotations=annotations,
            http_endpoints=HttpEndpointExtractor.extract(entities, annotations),
            jpa_entities=jpa_entities,
            spring_data_repositories=spring_data_repositories,
        )

    # -- naming -------------------------------------------------------------

    @staticmethod
    def _text(node: "Node", content: bytes) -> str:
        return content[node.start_byte : node.end_byte].decode("utf-8", "replace")

    @staticmethod
    def _collapse(text: str) -> str:
        return _WHITESPACE_RE.sub(" ", text).strip()

    @classmethod
    def _package_name(cls, root: "Node", content: bytes) -> str:
        for child in root.children:
            if child.type == "package_declaration":
                name = child.child_by_field_name("name") or child.children[1]
                return cls._text(name, content)
        return ""

    @classmethod
    def _same_file_type_names(
        cls, type_nodes: list["Node"], package: str, content: bytes
    ) -> dict[str, str]:
        """Simple name → qualified name for every type declared in this file,
        nested types included, so same-file `Type.method(...)` calls resolve.
        """
        names: dict[str, str] = {}

        def walk(node: "Node", parent_qualified_name: str | None) -> None:
            name_node = node.child_by_field_name("name")
            if name_node is None:
                return
            simple = cls._text(name_node, content)
            qualified_name = cls._join(parent_qualified_name or package, simple)
            names.setdefault(simple, qualified_name)
            body = node.child_by_field_name("body")
            if body is not None:
                for child in cls._body_members(body):
                    if child.type in _TYPE_KINDS:
                        walk(child, qualified_name)

        for type_node in type_nodes:
            walk(type_node, None)
        return names

    @staticmethod
    def _join(prefix: str, name: str) -> str:
        return f"{prefix}.{name}" if prefix else name

    # -- imports ----------------------------------------------------------

    @classmethod
    def _collect_imports(
        cls, root: "Node", content: bytes
    ) -> tuple[list[str], dict[str, str], dict[str, str]]:
        """Returns ``(imports, static_aliases, imported_types)``.

        ``imports`` is what feeds `IMPORTS` edges: a single-type import as the
        type FQN, an on-demand ``import x.y.*`` as the package ``x.y``, a
        static import as the member/type it names. ``static_aliases`` maps a
        statically-imported member's simple name to its FQN; ``imported_types``
        maps a single-type import's simple name to its FQN.
        """
        imports: list[str] = []
        static_aliases: dict[str, str] = {}
        imported_types: dict[str, str] = {}

        for child in root.children:
            if child.type != "import_declaration":
                continue
            is_static = any(grandchild.type == "static" for grandchild in child.children)
            on_demand = any(grandchild.type == "asterisk" for grandchild in child.children)
            path_node = next(
                (
                    grandchild
                    for grandchild in child.children
                    if grandchild.type in ("scoped_identifier", "identifier")
                ),
                None,
            )
            if path_node is None:
                continue
            dotted = cls._text(path_node, content)
            imports.append(dotted)
            simple = dotted.rsplit(".", 1)[-1]
            if is_static and not on_demand:
                static_aliases[simple] = dotted
            elif not is_static and not on_demand:
                imported_types[simple] = dotted
        return imports, static_aliases, imported_types

    # -- type + member entities -----------------------------------------

    @classmethod
    def _build_type_entities(
        cls,
        node: "Node",
        content: bytes,
        *,
        path: Path,
        parent_qualified_name: str | None,
        package_prefix: str,
        file_imports: list[str],
        static_aliases: dict[str, str],
        imported_types: dict[str, str],
        same_file_types: dict[str, str],
        annotations: list[Annotation],
    ) -> list[CodeEntity]:
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return []
        simple_name = cls._text(name_node, content)
        qualified_name = cls._join(parent_qualified_name or package_prefix, simple_name)
        kind = _TYPE_KINDS[node.type]
        body = node.child_by_field_name("body")

        member_nodes = (
            [child for child in cls._body_members(body) if child.type in _MEMBER_KINDS]
            if body
            else []
        )
        overloads: dict[str, list[str]] = {}
        for member in member_nodes:
            member_name = cls._member_simple_name(member, content, simple_name)
            overloads.setdefault(member_name, []).append(
                cls._member_qualified_name(member, content, qualified_name, simple_name)
            )

        signature = cls._type_signature(node, content, name_node, body)
        extends_types, implements_types = cls._supertypes(
            node, content, imported_types, same_file_types
        )
        field_names = cls._field_names(body, content) if body else []
        enum_constants = cls._enum_constant_names(body, content) if body else []
        docstring = cls._javadoc(node, content)
        embed_text = docstring or cls._type_summary(
            kind, simple_name, signature, field_names, enum_constants, list(overloads)
        )

        entities: list[CodeEntity] = [
            CodeEntity(
                qualified_name=qualified_name,
                name=simple_name,
                kind=kind,
                language="java",
                embed_text=embed_text,
                file_path=str(path),
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
                signature=signature or None,
                docstring=docstring,
                parent_qualified_name=parent_qualified_name,
                imports=file_imports,
                extends_types=extends_types,
                implements_types=implements_types,
            )
        ]
        cls._collect_annotations(
            node, content, qualified_name, "type", imported_types, same_file_types, annotations
        )
        entities.extend(
            LombokSynthesizer.synthesize(
                node,
                content,
                type_qualified_name=qualified_name,
                type_simple_name=simple_name,
                path=path,
                existing_members=set(overloads) | set(field_names),
            )
        )

        if body is None:
            return entities

        for child in cls._body_members(body):
            if child.type in _MEMBER_KINDS:
                entities.append(
                    cls._build_member_entity(
                        child,
                        content,
                        path=path,
                        type_qualified_name=qualified_name,
                        type_simple_name=simple_name,
                        overloads=overloads,
                        static_aliases=static_aliases,
                        imported_types=imported_types,
                        same_file_types=same_file_types,
                        annotations=annotations,
                    )
                )
            elif child.type == "field_declaration":
                entities.extend(
                    cls._build_field_entities(
                        child,
                        content,
                        path=path,
                        type_qualified_name=qualified_name,
                        type_simple_name=simple_name,
                        imported_types=imported_types,
                        same_file_types=same_file_types,
                        annotations=annotations,
                    )
                )
            elif child.type in _TYPE_KINDS:
                entities.extend(
                    cls._build_type_entities(
                        child,
                        content,
                        path=path,
                        parent_qualified_name=qualified_name,
                        package_prefix=package_prefix,
                        file_imports=[],
                        static_aliases=static_aliases,
                        imported_types=imported_types,
                        same_file_types=same_file_types,
                        annotations=annotations,
                    )
                )
        return entities

    @classmethod
    def _build_member_entity(
        cls,
        node: "Node",
        content: bytes,
        *,
        path: Path,
        type_qualified_name: str,
        type_simple_name: str,
        overloads: dict[str, list[str]],
        static_aliases: dict[str, str],
        imported_types: dict[str, str],
        same_file_types: dict[str, str],
        annotations: list[Annotation],
    ) -> CodeEntity:
        simple_name = cls._member_simple_name(node, content, type_simple_name)
        qualified_name = cls._member_qualified_name(
            node, content, type_qualified_name, type_simple_name
        )
        kind = _MEMBER_KINDS[node.type]
        body = node.child_by_field_name("body")
        signature = cls._member_signature(node, content, body)
        docstring = cls._javadoc(node, content)
        embed_text = docstring or cls._member_summary(kind, signature, body, content)
        calls = cls._resolve_calls(
            body,
            content,
            type_qualified_name=type_qualified_name,
            overloads=overloads,
            static_aliases=static_aliases,
            imported_types=imported_types,
            same_file_types=same_file_types,
        )
        target = "constructor" if kind == "constructor" else "method"
        cls._collect_annotations(
            node, content, qualified_name, target, imported_types, same_file_types, annotations
        )
        cls._collect_parameter_annotations(
            node.child_by_field_name("parameters"),
            content,
            qualified_name,
            imported_types,
            same_file_types,
            annotations,
        )
        return CodeEntity(
            qualified_name=qualified_name,
            name=simple_name,
            kind=kind,
            language="java",
            embed_text=embed_text,
            file_path=str(path),
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
            signature=signature or None,
            docstring=docstring,
            parent_qualified_name=type_qualified_name,
            calls=calls,
        )

    @classmethod
    def _build_field_entities(
        cls,
        node: "Node",
        content: bytes,
        *,
        path: Path,
        type_qualified_name: str,
        type_simple_name: str,
        imported_types: dict[str, str],
        same_file_types: dict[str, str],
        annotations: list[Annotation],
    ) -> list[CodeEntity]:
        """A `field` entity per declarator of an *annotated* field declaration.

        Unannotated fields stay folded into the owning type's `embed_text` via
        `_field_names` — they are never `CALLS`/`IMPORTS` endpoints, so a node
        would only inflate the graph.
        """
        annotation_nodes = cls._annotation_nodes(node)
        if not annotation_nodes:
            return []

        type_node = node.child_by_field_name("type")
        field_type = cls._collapse(cls._text(type_node, content)) if type_node is not None else "?"
        entities: list[CodeEntity] = []
        for declarator in node.children:
            if declarator.type != "variable_declarator":
                continue
            name_node = declarator.child_by_field_name("name")
            if name_node is None:
                continue
            field_name = cls._text(name_node, content)
            qualified_name = f"{type_qualified_name}#{field_name}"
            entities.append(
                CodeEntity(
                    qualified_name=qualified_name,
                    name=field_name,
                    kind="field",
                    language="java",
                    embed_text=f"field {field_type} {field_name} in {type_simple_name}",
                    file_path=str(path),
                    start_line=node.start_point[0] + 1,
                    end_line=node.end_point[0] + 1,
                    signature=cls._collapse(f"{field_type} {field_name}"),
                    parent_qualified_name=type_qualified_name,
                )
            )
            cls._add_annotations(
                annotation_nodes,
                content,
                qualified_name,
                "field",
                imported_types,
                same_file_types,
                annotations,
            )
        return entities

    # -- annotations ----------------------------------------------------

    @classmethod
    def _collect_annotations(
        cls,
        node: "Node",
        content: bytes,
        owner_qualified_name: str,
        target: str,
        imported_types: dict[str, str],
        same_file_types: dict[str, str],
        annotations: list[Annotation],
    ) -> None:
        cls._add_annotations(
            cls._annotation_nodes(node),
            content,
            owner_qualified_name,
            target,
            imported_types,
            same_file_types,
            annotations,
        )

    @classmethod
    def _collect_parameter_annotations(
        cls,
        parameters: "Node | None",
        content: bytes,
        method_qualified_name: str,
        imported_types: dict[str, str],
        same_file_types: dict[str, str],
        annotations: list[Annotation],
    ) -> None:
        if parameters is None:
            return
        for child in parameters.children:
            if child.type not in ("formal_parameter", "spread_parameter"):
                continue
            annotation_nodes = cls._annotation_nodes(child)
            if not annotation_nodes:
                continue
            name_node = child.child_by_field_name("name")
            param_name = cls._text(name_node, content) if name_node is not None else "?"
            cls._add_annotations(
                annotation_nodes,
                content,
                method_qualified_name,
                f"param:{param_name}",
                imported_types,
                same_file_types,
                annotations,
            )

    @staticmethod
    def _annotation_nodes(node: "Node") -> list["Node"]:
        modifiers = next((child for child in node.children if child.type == "modifiers"), None)
        if modifiers is None:
            return []
        return [child for child in modifiers.children if child.type in _ANNOTATION_NODE_TYPES]

    @classmethod
    def _add_annotations(
        cls,
        annotation_nodes: list["Node"],
        content: bytes,
        owner_qualified_name: str,
        target: str,
        imported_types: dict[str, str],
        same_file_types: dict[str, str],
        annotations: list[Annotation],
    ) -> None:
        for annotation_node in annotation_nodes:
            name, fqn, attributes, line = cls._parse_annotation(
                annotation_node, content, imported_types, same_file_types
            )
            annotations.append(
                Annotation(
                    owner_qualified_name=owner_qualified_name,
                    target=target,
                    name=name,
                    fqn=fqn,
                    line=line,
                    attributes=attributes,
                )
            )

    @classmethod
    def _parse_annotation(
        cls,
        node: "Node",
        content: bytes,
        imported_types: dict[str, str],
        same_file_types: dict[str, str],
    ) -> tuple[str, str, dict[str, Any], int]:
        name_node = node.child_by_field_name("name")
        raw_name = cls._text(name_node, content) if name_node is not None else ""
        simple_name = raw_name.rsplit(".", 1)[-1]
        if "." in raw_name:
            fqn = raw_name
        else:
            fqn = imported_types.get(simple_name) or same_file_types.get(simple_name) or simple_name

        attributes: dict[str, Any] = {}
        arguments = node.child_by_field_name("arguments")
        if arguments is not None:
            pairs = [child for child in arguments.children if child.type == "element_value_pair"]
            if pairs:
                for pair in pairs:
                    key_node = pair.child_by_field_name("key")
                    key = cls._text(key_node, content) if key_node is not None else "value"
                    attributes[key] = cls._parse_element_value(
                        pair.child_by_field_name("value"), content, imported_types, same_file_types
                    )
            else:
                value_node = next((child for child in arguments.children if child.is_named), None)
                if value_node is not None:
                    attributes["value"] = cls._parse_element_value(
                        value_node, content, imported_types, same_file_types
                    )
        return simple_name, fqn, attributes, node.start_point[0] + 1

    @classmethod
    def _parse_element_value(
        cls,
        node: "Node | None",
        content: bytes,
        imported_types: dict[str, str],
        same_file_types: dict[str, str],
    ) -> Any:
        if node is None:
            return None
        node_type = node.type
        if node_type == "string_literal":
            text = cls._text(node, content)
            if len(text) >= 2 and text[0] == '"' and text[-1] == '"':
                return text[1:-1]
            return text
        if node_type in _INTEGER_LITERALS:
            raw = cls._text(node, content).rstrip("lL").replace("_", "")
            try:
                return int(raw, 0)
            except ValueError:
                return cls._text(node, content)
        if node_type in _FLOAT_LITERALS:
            raw = cls._text(node, content).rstrip("fFdD").replace("_", "")
            try:
                return float(raw)
            except ValueError:
                return cls._text(node, content)
        if node_type == "true":
            return True
        if node_type == "false":
            return False
        if node_type == "element_value_array_initializer":
            return [
                cls._parse_element_value(child, content, imported_types, same_file_types)
                for child in node.children
                if child.is_named
            ]
        if node_type in _ANNOTATION_NODE_TYPES:
            nested_name, _fqn, nested_attributes, _line = cls._parse_annotation(
                node, content, imported_types, same_file_types
            )
            if nested_attributes:
                return {f"@{nested_name}": nested_attributes}
            return f"@{nested_name}"
        # class literal (`Foo.class`), enum constant (`RetentionPolicy.RUNTIME`),
        # a constant reference, or an expression we don't evaluate — keep the text.
        return cls._collapse(cls._text(node, content))

    @classmethod
    def _member_simple_name(cls, node: "Node", content: bytes, type_simple_name: str) -> str:
        name_node = node.child_by_field_name("name")
        return cls._text(name_node, content) if name_node is not None else type_simple_name

    @classmethod
    def _member_qualified_name(
        cls, node: "Node", content: bytes, type_qualified_name: str, type_simple_name: str
    ) -> str:
        simple_name = cls._member_simple_name(node, content, type_simple_name)
        params = cls._parameter_types(node.child_by_field_name("parameters"), content)
        return f"{type_qualified_name}.{simple_name}({','.join(params)})"

    @classmethod
    def _parameter_types(cls, parameters: "Node | None", content: bytes) -> list[str]:
        if parameters is None:
            return []
        types: list[str] = []
        for child in parameters.children:
            if child.type not in ("formal_parameter", "spread_parameter"):
                continue
            type_node = child.child_by_field_name("type")
            if type_node is None:
                # spread_parameter has no `type` field — take its first type-ish child.
                type_node = next(
                    (grandchild for grandchild in child.children if grandchild.is_named), None
                )
            text = cls._collapse(cls._text(type_node, content)) if type_node is not None else "?"
            if child.type == "spread_parameter":
                text += "..."
            types.append(text.replace(" ", ""))
        return types

    # -- signatures / summaries ---------------------------------------

    @classmethod
    def _type_signature(
        cls, node: "Node", content: bytes, name_node: "Node", body: "Node | None"
    ) -> str:
        end_byte = body.start_byte if body is not None else node.end_byte
        return cls._collapse(content[name_node.end_byte : end_byte].decode("utf-8", "replace"))

    @classmethod
    def _member_signature(cls, node: "Node", content: bytes, body: "Node | None") -> str:
        end_byte = body.start_byte if body is not None else node.end_byte
        text = cls._collapse(content[node.start_byte : end_byte].decode("utf-8", "replace"))
        return text.rstrip("{;").strip()

    @staticmethod
    def _body_members(body: "Node") -> list["Node"]:
        """The member declarations of a type body. For an `enum_body`,
        tree-sitter-java nests methods / fields / nested types inside an
        `enum_body_declarations` child (the constants stay direct); flatten it
        so enum members are walked like any class's.
        """
        members: list[Node] = []
        for child in body.children:
            if child.type == "enum_body_declarations":
                members.extend(child.children)
            else:
                members.append(child)
        return members

    @classmethod
    def _field_names(cls, body: "Node", content: bytes) -> list[str]:
        names: list[str] = []
        for child in cls._body_members(body):
            if child.type != "field_declaration":
                continue
            for declarator in child.children:
                if declarator.type == "variable_declarator":
                    name_node = declarator.child_by_field_name("name")
                    if name_node is not None:
                        names.append(cls._text(name_node, content))
        return names

    # -- supertypes ---------------------------------------------------

    @classmethod
    def _supertypes(
        cls,
        node: "Node",
        content: bytes,
        imported_types: dict[str, str],
        same_file_types: dict[str, str],
    ) -> tuple[list[str], list[str]]:
        """`(extends, implements)` for a type node — a class's `extends`
        superclass and an interface's `extends` super-interfaces both count as
        `extends`; `implements` (and an enum/record's) as `implements`. Names
        are FQN-resolved against the file's imports, else kept simple.
        """
        extends_types: list[str] = []
        implements_types: list[str] = []
        for child in node.children:
            if child.type in ("superclass", "extends_interfaces"):
                bucket = extends_types
            elif child.type == "super_interfaces":
                bucket = implements_types
            else:
                continue
            for type_node in cls._type_list_members(child):
                bucket.append(
                    cls._resolve_type_name(
                        cls._type_name_text(type_node, content), imported_types, same_file_types
                    )
                )
        return extends_types, implements_types

    @staticmethod
    def _type_list_members(container: "Node") -> list["Node"]:
        members: list[Node] = []
        for child in container.children:
            if child.type == "type_list":
                members.extend(grandchild for grandchild in child.children if grandchild.is_named)
            elif child.is_named and child.type not in ("extends", "implements"):
                members.append(child)
        return members

    @classmethod
    def _type_name_text(cls, node: "Node", content: bytes) -> str:
        if node.type == "generic_type" and node.children:
            return cls._type_name_text(node.children[0], content)
        return cls._collapse(cls._text(node, content))

    @staticmethod
    def _resolve_type_name(
        raw_name: str, imported_types: dict[str, str], same_file_types: dict[str, str]
    ) -> str:
        if "." in raw_name:
            return raw_name
        return imported_types.get(raw_name) or same_file_types.get(raw_name) or raw_name

    # -- Spring Data repository bindings -----------------------------

    @classmethod
    def _collect_repo_bindings(
        cls,
        type_nodes: list["Node"],
        content: bytes,
        package: str,
        imported_types: dict[str, str],
        same_file_types: dict[str, str],
    ) -> dict[str, dict[str, Any]]:
        """`{interface qualified_name: {base, entity_type, id_type, reactive}}`
        for every interface extending a recognised Spring Data base. The generic
        type arguments (`JpaRepository<Order, Long>`) live only in the AST —
        `CodeEntity.extends_types` has already dropped them.
        """
        bindings: dict[str, dict[str, Any]] = {}

        def walk(node: "Node", parent_qualified_name: str | None) -> None:
            name_node = node.child_by_field_name("name")
            if name_node is None:
                return
            qualified_name = cls._join(
                parent_qualified_name or package, cls._text(name_node, content)
            )
            if node.type == "interface_declaration":
                binding = cls._repository_binding(node, content, imported_types, same_file_types)
                if binding is not None:
                    bindings[qualified_name] = binding
            body = node.child_by_field_name("body")
            if body is not None:
                for child in cls._body_members(body):
                    if child.type in _TYPE_KINDS:
                        walk(child, qualified_name)

        for type_node in type_nodes:
            walk(type_node, None)
        return bindings

    @classmethod
    def _repository_binding(
        cls,
        node: "Node",
        content: bytes,
        imported_types: dict[str, str],
        same_file_types: dict[str, str],
    ) -> dict[str, Any] | None:
        best: dict[str, Any] | None = None
        for child in node.children:
            if child.type not in ("extends_interfaces", "super_interfaces"):
                continue
            for member in cls._type_list_members(child):
                if member.type != "generic_type" or not member.children:
                    continue
                base = cls._collapse(cls._text(member.children[0], content))
                base = base.split("<", 1)[0].rsplit(".", 1)[-1].strip()
                if base not in SPRING_DATA_BASES:
                    continue
                args = cls._generic_type_args(member, content, imported_types, same_file_types)
                candidate = {
                    "base": base,
                    "entity_type": args[0] if args else None,
                    "id_type": args[1] if len(args) > 1 else None,
                    "reactive": base in REACTIVE_BASES,
                }
                if best is None or (candidate["id_type"] and not best["id_type"]):
                    best = candidate
        return best

    @classmethod
    def _generic_type_args(
        cls,
        generic_node: "Node",
        content: bytes,
        imported_types: dict[str, str],
        same_file_types: dict[str, str],
    ) -> list[str]:
        for child in generic_node.children:
            if child.type == "type_arguments":
                return [
                    cls._resolve_type_name(
                        cls._type_name_text(arg, content), imported_types, same_file_types
                    )
                    for arg in child.children
                    if arg.is_named
                ]
        return []

    @classmethod
    def _enum_constant_names(cls, body: "Node", content: bytes) -> list[str]:
        return [
            cls._text(child.child_by_field_name("name"), content)
            for child in body.children
            if child.type == "enum_constant" and child.child_by_field_name("name") is not None
        ]

    @classmethod
    def _javadoc(cls, node: "Node", content: bytes) -> str | None:
        sibling = node.prev_named_sibling
        if sibling is None or sibling.type != "block_comment":
            return None
        raw = cls._text(sibling, content)
        if not raw.startswith("/**"):
            return None
        inner = raw[3:]
        inner = inner[:-2] if inner.endswith("*/") else inner
        lines = [line.strip().lstrip("*").strip() for line in inner.splitlines()]
        return " ".join(line for line in lines if line) or None

    @staticmethod
    def _type_summary(
        kind: str,
        name: str,
        signature: str,
        field_names: list[str],
        enum_constants: list[str],
        method_names: list[str],
    ) -> str:
        summary = f"{kind} {name} {signature}".strip()
        if enum_constants:
            summary += f". Constants: {', '.join(enum_constants)}"
        if field_names:
            summary += f". Fields: {', '.join(field_names)}"
        if method_names:
            summary += f". Methods: {', '.join(method_names)}"
        return summary

    @classmethod
    def _member_summary(cls, kind: str, signature: str, body: "Node | None", content: bytes) -> str:
        first_line = ""
        if body is not None:
            statement = next((child for child in body.children if child.is_named), None)
            if statement is not None:
                first_line = cls._collapse(cls._text(statement, content)).splitlines()[0]
        summary = f"{kind} {signature}".strip()
        return f"{summary}: {first_line}" if first_line else summary

    # -- calls ------------------------------------------------------------

    @classmethod
    def _resolve_calls(
        cls,
        body: "Node | None",
        content: bytes,
        *,
        type_qualified_name: str,
        overloads: dict[str, list[str]],
        static_aliases: dict[str, str],
        imported_types: dict[str, str],
        same_file_types: dict[str, str],
    ) -> list[str]:
        if body is None:
            return []
        resolved: dict[str, None] = {}
        for invocation in cls._descendants(body):
            if invocation.type != "method_invocation":
                continue
            name_node = invocation.child_by_field_name("name")
            if name_node is None:
                continue
            method_name = cls._text(name_node, content)
            receiver = invocation.child_by_field_name("object")

            if receiver is None:
                target = cls._only_overload(overloads, method_name) or static_aliases.get(
                    method_name
                )
            elif receiver.type in ("this", "super"):
                target = cls._only_overload(overloads, method_name)
            elif receiver.type == "identifier":
                receiver_name = cls._text(receiver, content)
                type_qn = imported_types.get(receiver_name) or same_file_types.get(receiver_name)
                target = f"{type_qn}.{method_name}" if type_qn else None
            else:
                target = None  # call on a field access / expression result — skip.

            if target:
                resolved[target] = None
        return list(resolved)

    @staticmethod
    def _only_overload(overloads: dict[str, list[str]], method_name: str) -> str | None:
        candidates = overloads.get(method_name, [])
        return candidates[0] if len(candidates) == 1 else None

    @classmethod
    def _descendants(cls, node: "Node"):
        for child in node.children:
            yield child
            yield from cls._descendants(child)
