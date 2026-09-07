import re
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

from ..models import CodeEntity

if TYPE_CHECKING:
    from tree_sitter import Node

_WHITESPACE_RE = re.compile(r"\s+")
_ORIGIN = "lombok"

# Lombok annotations whose synthesized members we can name without a build.
_GETTER = {"Getter", "Data", "Value"}
_SETTER = {"Setter", "Data"}  # `@Value` is immutable — no setters
_NO_ARGS = {"NoArgsConstructor"}
_ALL_ARGS = {"AllArgsConstructor", "Value"}
_REQUIRED_ARGS = {"RequiredArgsConstructor", "Data"}
_BUILDER = {"Builder"}
_LOG_FIELD = {
    "Slf4j",
    "Log",
    "Log4j",
    "Log4j2",
    "CommonsLog",
    "JBossLog",
    "Flogger",
    "XSlf4j",
}
_ALL_LOMBOK = _GETTER | _SETTER | _NO_ARGS | _ALL_ARGS | _REQUIRED_ARGS | _BUILDER | _LOG_FIELD


class _Field(NamedTuple):
    name: str
    type: str
    is_final: bool
    is_static: bool
    has_initializer: bool
    is_non_null: bool


class LombokSynthesizer:
    """Materialises the `CodeEntity`s that Lombok annotations would generate at
    compile time, so tree-sitter's source-only view still shows the accessors,
    constructors, `log` field, and builder that enterprise code calls into (and
    that Spring injects through).

    Best-effort and single-file: a field that already has an explicit
    accessor/constructor of the same shape is left alone, unknown annotations
    are ignored, and every emitted entity is flagged `synthetic=True`,
    `origin="lombok"`.
    """

    @classmethod
    def synthesize(
        cls,
        type_node: "Node",
        content: bytes,
        *,
        type_qualified_name: str,
        type_simple_name: str,
        path: Path,
        existing_members: set[str],
    ) -> list[CodeEntity]:
        markers = cls._type_annotations(type_node, content)
        if markers.isdisjoint(_ALL_LOMBOK):
            return []

        body = type_node.child_by_field_name("body")
        if body is None:
            return []
        fields = cls._fields(body, content)
        instance_fields = [field for field in fields if not field.is_static]
        line = type_node.start_point[0] + 1

        emitted: dict[str, CodeEntity] = {}

        def add(entity: CodeEntity) -> None:
            emitted.setdefault(entity.qualified_name, entity)

        for entity in cls._accessors(
            markers,
            instance_fields,
            type_qualified_name,
            type_simple_name,
            path,
            line,
            existing_members,
        ):
            add(entity)
        for entity in cls._constructors(
            markers,
            instance_fields,
            type_qualified_name,
            type_simple_name,
            path,
            line,
            existing_members,
        ):
            add(entity)
        builder = cls._builder(
            markers, type_qualified_name, type_simple_name, path, line, existing_members
        )
        for entity in builder:
            add(entity)
        log = cls._log_field(
            markers, type_qualified_name, type_simple_name, path, line, existing_members
        )
        if log is not None:
            add(log)
        return list(emitted.values())

    # -- accessors --

    @classmethod
    def _accessors(
        cls,
        markers: set[str],
        fields: list[_Field],
        type_qn: str,
        type_name: str,
        path: Path,
        line: int,
        existing: set[str],
    ) -> list[CodeEntity]:
        entities: list[CodeEntity] = []
        want_get = bool(markers & _GETTER)
        want_set = bool(markers & _SETTER) and "Value" not in markers
        for field in fields:
            capitalized = field.name[:1].upper() + field.name[1:]
            if want_get:
                verb = "is" if field.type == "boolean" else "get"
                getter = f"{verb}{capitalized}"
                if getter not in existing:
                    entities.append(
                        cls._method(
                            type_qn,
                            type_name,
                            path,
                            line,
                            name=getter,
                            params=[],
                            returns=field.type,
                            summary=f"{field.type} {getter}() for field {field.name}",
                        )
                    )
            if want_set and not field.is_final:
                setter = f"set{capitalized}"
                if setter not in existing:
                    entities.append(
                        cls._method(
                            type_qn,
                            type_name,
                            path,
                            line,
                            name=setter,
                            params=[field.type],
                            returns="void",
                            summary=f"void {setter}({field.type}) for field {field.name}",
                        )
                    )
        return entities

    # -- constructors --

    @classmethod
    def _constructors(
        cls,
        markers: set[str],
        fields: list[_Field],
        type_qn: str,
        type_name: str,
        path: Path,
        line: int,
        existing: set[str],
    ) -> list[CodeEntity]:
        has_explicit_constructor = type_name in existing
        entities: list[CodeEntity] = []
        if markers & _NO_ARGS:
            entities.append(cls._constructor(type_qn, type_name, path, line, params=[]))
        if markers & _ALL_ARGS:
            entities.append(
                cls._constructor(type_qn, type_name, path, line, params=[f.type for f in fields])
            )
        required = [
            field.type
            for field in fields
            if (field.is_final and not field.has_initializer) or field.is_non_null
        ]
        # `@Data` only synthesizes the required-args constructor when the class
        # declares no constructor of its own and no other `*ArgsConstructor`.
        wants_required = bool(markers & {"RequiredArgsConstructor"}) or (
            "Data" in markers
            and not has_explicit_constructor
            and not markers & (_NO_ARGS | {"AllArgsConstructor"})
        )
        if wants_required:
            entities.append(cls._constructor(type_qn, type_name, path, line, params=required))
        return entities

    # -- builder --

    @classmethod
    def _builder(
        cls,
        markers: set[str],
        type_qn: str,
        type_name: str,
        path: Path,
        line: int,
        existing: set[str],
    ) -> list[CodeEntity]:
        if not markers & _BUILDER:
            return []
        builder_name = f"{type_name}Builder"
        entities = [
            CodeEntity(
                qualified_name=f"{type_qn}.{builder_name}",
                name=builder_name,
                kind="class",
                language="java",
                embed_text=f"Lombok builder for {type_name}",
                file_path=str(path),
                start_line=line,
                end_line=line,
                parent_qualified_name=type_qn,
                synthetic=True,
                origin=_ORIGIN,
            )
        ]
        if "builder" not in existing:
            entities.append(
                cls._method(
                    type_qn,
                    type_name,
                    path,
                    line,
                    name="builder",
                    params=[],
                    returns=builder_name,
                    summary=f"{builder_name} builder()",
                )
            )
        return entities

    # -- log field --

    @classmethod
    def _log_field(
        cls,
        markers: set[str],
        type_qn: str,
        type_name: str,
        path: Path,
        line: int,
        existing: set[str],
    ) -> CodeEntity | None:
        if not markers & _LOG_FIELD or "log" in existing:
            return None
        return CodeEntity(
            qualified_name=f"{type_qn}#log",
            name="log",
            kind="field",
            language="java",
            embed_text=f"Lombok logger field log in {type_name}",
            file_path=str(path),
            start_line=line,
            end_line=line,
            signature="Logger log",
            parent_qualified_name=type_qn,
            synthetic=True,
            origin=_ORIGIN,
        )

    # -- entity factories --

    @classmethod
    def _method(
        cls,
        type_qn: str,
        type_name: str,
        path: Path,
        line: int,
        *,
        name: str,
        params: list[str],
        returns: str,
        summary: str,
    ) -> CodeEntity:
        joined = ",".join(param.replace(" ", "") for param in params)
        return CodeEntity(
            qualified_name=f"{type_qn}.{name}({joined})",
            name=name,
            kind="method",
            language="java",
            embed_text=summary,
            file_path=str(path),
            start_line=line,
            end_line=line,
            signature=f"{returns} {name}({', '.join(params)})",
            parent_qualified_name=type_qn,
            synthetic=True,
            origin=_ORIGIN,
        )

    @classmethod
    def _constructor(
        cls, type_qn: str, type_name: str, path: Path, line: int, *, params: list[str]
    ) -> CodeEntity:
        joined = ",".join(param.replace(" ", "") for param in params)
        return CodeEntity(
            qualified_name=f"{type_qn}.{type_name}({joined})",
            name=type_name,
            kind="constructor",
            language="java",
            embed_text=f"{type_name}({', '.join(params)})",
            file_path=str(path),
            start_line=line,
            end_line=line,
            signature=f"{type_name}({', '.join(params)})",
            parent_qualified_name=type_qn,
            synthetic=True,
            origin=_ORIGIN,
        )

    # -- tree-sitter extraction --

    @classmethod
    def _type_annotations(cls, type_node: "Node", content: bytes) -> set[str]:
        modifiers = next((child for child in type_node.children if child.type == "modifiers"), None)
        if modifiers is None:
            return set()
        names: set[str] = set()
        for child in modifiers.children:
            if child.type not in ("marker_annotation", "annotation"):
                continue
            name_node = child.child_by_field_name("name")
            if name_node is not None:
                names.add(cls._text(name_node, content).rsplit(".", 1)[-1])
        return names

    @classmethod
    def _fields(cls, body: "Node", content: bytes) -> list[_Field]:
        fields: list[_Field] = []
        for child in body.children:
            if child.type != "field_declaration":
                continue
            modifiers = next((c for c in child.children if c.type == "modifiers"), None)
            keyword_types = {c.type for c in modifiers.children} if modifiers is not None else set()
            annotation_names = (
                {
                    cls._text(c.child_by_field_name("name"), content).rsplit(".", 1)[-1]
                    for c in modifiers.children
                    if c.type in ("marker_annotation", "annotation")
                    and c.child_by_field_name("name") is not None
                }
                if modifiers is not None
                else set()
            )
            type_node = child.child_by_field_name("type")
            field_type = (
                cls._collapse(cls._text(type_node, content)) if type_node is not None else "?"
            )
            for declarator in child.children:
                if declarator.type != "variable_declarator":
                    continue
                name_node = declarator.child_by_field_name("name")
                if name_node is None:
                    continue
                fields.append(
                    _Field(
                        name=cls._text(name_node, content),
                        type=field_type,
                        is_final="final" in keyword_types,
                        is_static="static" in keyword_types,
                        has_initializer=declarator.child_by_field_name("value") is not None,
                        is_non_null=bool(annotation_names & {"NonNull", "NotNull"}),
                    )
                )
        return fields

    @staticmethod
    def _text(node: "Node", content: bytes) -> str:
        return content[node.start_byte : node.end_byte].decode("utf-8", "replace")

    @classmethod
    def _collapse(cls, text: str) -> str:
        return _WHITESPACE_RE.sub(" ", text).strip()
