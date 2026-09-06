import hashlib
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from ..models import CodeEntity, ParsedDocument, Source

if TYPE_CHECKING:
    from tree_sitter import Node

_WHITESPACE_RE = re.compile(r"\s+")

# One parser for JavaScript, TypeScript, and their JSX variants — they are
# grammar variants of the same tree-sitter parse, not separate languages.
_JS_SUFFIXES = {".js", ".mjs", ".cjs", ".jsx"}
_TS_SUFFIXES = {".ts", ".tsx"}
_SUFFIXES = _JS_SUFFIXES | _TS_SUFFIXES

# `.ts`/`.tsx` need the typescript / tsx grammars; everything else (JSX
# included) is handled by the javascript grammar.
_GRAMMAR_BY_SUFFIX = {".ts": "typescript", ".tsx": "tsx"}

# Extensions stripped when turning a module path or a relative import
# specifier into a dotted `qualified_name`. `.d.ts` before `.ts` so the
# longer match wins.
_MODULE_SUFFIXES = (".d.ts", ".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx", ".json")

# A directory holding one of these is treated as the project root that
# module `qualified_name`s are made relative to.
_PROJECT_MARKERS = ("package.json", "tsconfig.json", "jsconfig.json")

# TypeScript-only type declarations → the `CodeEntity.kind` we emit.
_TYPE_DECL_KINDS: dict[str, str] = {
    "class_declaration": "class",
    "abstract_class_declaration": "class",
    "interface_declaration": "interface",
    "type_alias_declaration": "type",
    "enum_declaration": "enum",
}
_FUNCTION_DECL_TYPES = {"function_declaration", "generator_function_declaration"}
_FUNCTION_VALUE_TYPES = {"arrow_function", "function", "function_expression"}


class JavaScriptParser:
    """Parses a `.js/.mjs/.cjs/.jsx/.ts/.tsx` file into a `Source` + `CodeEntity`
    list via tree-sitter — JavaScript and TypeScript in one parser.

    The file is a `module` entity (its `imports` feed `IMPORTS` edges);
    top-level functions, classes (+ their methods), and exported
    arrow/function `const`s become `CodeEntity` nodes, as do TypeScript
    `interface` / `type` / `enum` declarations (signature only — their
    members are not emitted as entities).

    `qualified_name` is the module's project-relative path, dotted and without
    extension (`src.orders.order_service`), with members dotted onto it
    (`src.orders.order_service.OrderService.submit`). Relative import
    specifiers (`./`, `../`) are resolved against the project tree to the same
    dotted form; bare specifiers (`react`, `lodash`) are kept verbatim.
    `calls`/`imports` are best-effort static only — a call on an arbitrary
    member-expression result is skipped rather than guessed, matching
    `PythonParser`.
    """

    @staticmethod
    def can_handle(path: Path) -> bool:
        return path.suffix.lower() in _SUFFIXES

    def parse(self, path: Path) -> ParsedDocument:
        try:
            from tree_sitter_language_pack import get_parser
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "Parsing JavaScript/TypeScript needs the optional 'js' extra. Install it with "
                "`pip install 'grag-mcp[js]'` (or `uv sync --extra js`)."
            ) from exc

        content = path.read_bytes()
        suffix = path.suffix.lower()
        language = "typescript" if suffix in _TS_SUFFIXES else "javascript"
        source = Source(
            path=str(path),
            source_type=language,
            content_hash=hashlib.sha256(content).hexdigest(),
            ingested_at=datetime.now(UTC),
        )

        grammar = _GRAMMAR_BY_SUFFIX.get(suffix, "javascript")
        root = get_parser(grammar).parse(content).root_node

        project_root = self._project_root(path)
        module_qualified_name = self._module_qualified_name(path, project_root)
        imports, import_bindings = self._collect_imports(root, content, path, project_root)

        declarations = self._top_level_declarations(root, content)
        local_top_level = {name for _, name, _ in declarations}

        text = content.decode("utf-8", "replace")
        first_child = root.children[0] if root.children else None
        module_docstring = (
            self._parse_jsdoc_comment(self._text(first_child, content))
            if first_child is not None and first_child.type == "comment"
            else None
        )
        module_embed_text = module_docstring or self._module_summary(
            module_qualified_name, local_top_level
        )
        entities: list[CodeEntity] = [
            CodeEntity(
                qualified_name=module_qualified_name,
                name=module_qualified_name.rsplit(".", 1)[-1],
                kind="module",
                language=language,
                embed_text=module_embed_text,
                file_path=str(path),
                start_line=1,
                end_line=len(text.splitlines()) or 1,
                docstring=module_docstring,
                imports=imports,
            )
        ]

        for node, name, kind in declarations:
            if kind == "class":
                entities.extend(
                    self._build_class_entities(
                        node,
                        content,
                        path=path,
                        language=language,
                        module_qualified_name=module_qualified_name,
                        local_top_level=local_top_level,
                        import_bindings=import_bindings,
                    )
                )
            elif kind == "function":
                entities.append(
                    self._build_function_entity(
                        node,
                        content,
                        path=path,
                        language=language,
                        kind="function",
                        parent_qualified_name=module_qualified_name,
                        module_qualified_name=module_qualified_name,
                        local_top_level=local_top_level,
                        import_bindings=import_bindings,
                        class_qualified_name=None,
                        class_method_names=set(),
                        name_override=name,
                    )
                )
            else:
                entities.append(
                    self._build_type_entity(
                        node,
                        content,
                        path=path,
                        language=language,
                        kind=kind,
                        module_qualified_name=module_qualified_name,
                    )
                )

        return ParsedDocument(source=source, code_entities=entities)

    # -- module naming --------------------------------------------------

    @staticmethod
    def _project_root(path: Path) -> Path:
        for parent in [path.parent, *path.parent.parents]:
            if any((parent / marker).is_file() for marker in _PROJECT_MARKERS):
                return parent
        return path.parent

    @classmethod
    def _module_qualified_name(cls, path: Path, project_root: Path) -> str:
        target = cls._strip_module_suffix(path)
        dotted = cls._dotted_relative(target, project_root)
        return dotted or path.stem

    @staticmethod
    def _strip_module_suffix(path: Path) -> Path:
        name = path.name
        for suffix in _MODULE_SUFFIXES:
            if name.endswith(suffix) and len(name) > len(suffix):
                return path.with_name(name[: -len(suffix)])
        return path

    @staticmethod
    def _dotted_relative(target: Path, project_root: Path) -> str:
        # `index` is the directory's implicit module — drop the segment.
        if target.name == "index":
            target = target.parent
        try:
            parts = target.relative_to(project_root).parts
        except ValueError:
            parts = tuple(part for part in target.parts if part not in ("", "..", "."))[-4:]
        return ".".join(parts)

    @classmethod
    def _resolve_specifier(cls, specifier: str, path: Path, project_root: Path) -> str:
        if not specifier.startswith("."):
            return specifier  # bare specifier (`react`, `@scope/pkg`) — leave as-is.
        target = path.parent
        for part in specifier.split("/"):
            if part in ("", "."):
                continue
            target = target.parent if part == ".." else target / part
        target = cls._strip_module_suffix(target)
        return cls._dotted_relative(target, project_root) or target.name

    # -- imports ------------------------------------------------------

    @classmethod
    def _collect_imports(
        cls, root: "Node", content: bytes, path: Path, project_root: Path
    ) -> tuple[list[str], dict[str, str]]:
        """Returns ``(imports, import_bindings)``.

        ``imports`` is every specifier the file references, resolved and
        de-duplicated in source order — it feeds `IMPORTS` edges.
        ``import_bindings`` maps a locally-bound name to the target a call
        through it resolves to: a named import to ``module.symbol``, a
        default / namespace / `require` binding to the module itself.
        """
        imports: dict[str, None] = {}
        bindings: dict[str, str] = {}

        def record(specifier: str) -> str:
            resolved = cls._resolve_specifier(specifier, path, project_root)
            imports[resolved] = None
            return resolved

        for child in root.children:
            if child.type == "import_statement":
                source_node = child.child_by_field_name("source")
                if source_node is None:
                    continue
                resolved = cls._resolve_specifier(
                    cls._string_value(source_node, content), path, project_root
                )
                clause = next((kid for kid in child.children if kid.type == "import_clause"), None)
                names = (
                    cls._bind_import_clause(clause, content, resolved, bindings)
                    if clause is not None
                    else [resolved]  # side-effect `import "x"`
                )
                for name in names:
                    imports[name] = None
            elif child.type == "export_statement":
                source_node = child.child_by_field_name("source")
                if source_node is not None:
                    resolved = cls._resolve_specifier(
                        cls._string_value(source_node, content), path, project_root
                    )
                    for name in cls._reexport_names(child, content, resolved):
                        imports[name] = None
            elif child.type in ("lexical_declaration", "variable_declaration"):
                cls._bind_require_declaration(child, content, path, project_root, imports, bindings)

        # Dynamic `import("x")` and nested `require("x")` anywhere in the file.
        for node in cls._descendants(root):
            if node.type != "call_expression":
                continue
            callee = node.child_by_field_name("function")
            if callee is None or callee.type not in ("import", "identifier"):
                continue
            if callee.type == "identifier" and cls._text(callee, content) != "require":
                continue
            argument = cls._first_string_argument(node, content)
            if argument is not None:
                record(argument)

        return list(imports), bindings

    @classmethod
    def _bind_import_clause(
        cls, clause: "Node", content: bytes, resolved: str, bindings: dict[str, str]
    ) -> list[str]:
        """Populates ``bindings`` for the clause and returns the specifiers it
        contributes to ``imports`` — ``module.symbol`` for each named import,
        the bare module for a default or namespace import.
        """
        specifiers: list[str] = []
        for child in clause.children:
            if child.type == "identifier":  # default import
                bindings[cls._text(child, content)] = resolved
                specifiers.append(resolved)
            elif child.type == "namespace_import":
                alias = next((kid for kid in child.children if kid.type == "identifier"), None)
                if alias is not None:
                    bindings[cls._text(alias, content)] = resolved
                specifiers.append(resolved)
            elif child.type == "named_imports":
                for specifier in child.children:
                    if specifier.type != "import_specifier":
                        continue
                    names = [kid for kid in specifier.children if kid.type == "identifier"]
                    imported = cls._text(names[0], content)
                    local = cls._text(names[-1], content)
                    bindings[local] = f"{resolved}.{imported}"
                    specifiers.append(f"{resolved}.{imported}")
        return specifiers or [resolved]

    @classmethod
    def _reexport_names(cls, export_statement: "Node", content: bytes, resolved: str) -> list[str]:
        """``module.symbol`` for each name in `export { a, b } from "module"`;
        the bare module for `export * from "module"`.
        """
        clause = next(
            (kid for kid in export_statement.children if kid.type == "export_clause"), None
        )
        if clause is None:
            return [resolved]
        names: list[str] = []
        for specifier in clause.children:
            if specifier.type != "export_specifier":
                continue
            identifier = next((kid for kid in specifier.children if kid.type == "identifier"), None)
            if identifier is not None:
                names.append(f"{resolved}.{cls._text(identifier, content)}")
        return names or [resolved]

    @classmethod
    def _bind_require_declaration(
        cls,
        declaration: "Node",
        content: bytes,
        path: Path,
        project_root: Path,
        imports: dict[str, None],
        bindings: dict[str, str],
    ) -> None:
        for declarator in declaration.children:
            if declarator.type != "variable_declarator":
                continue
            value = declarator.child_by_field_name("value")
            specifier = cls._require_specifier(value, content) if value is not None else None
            if specifier is None:
                continue
            resolved = cls._resolve_specifier(specifier, path, project_root)
            imports[resolved] = None
            target = declarator.child_by_field_name("name")
            if target is None:
                continue
            if target.type == "identifier":
                bindings[cls._text(target, content)] = resolved
            elif target.type == "object_pattern":
                for kid in target.children:
                    if kid.type == "shorthand_property_identifier_pattern":
                        name = cls._text(kid, content)
                        bindings[name] = f"{resolved}.{name}"

    @classmethod
    def _require_specifier(cls, value: "Node", content: bytes) -> str | None:
        node = value
        if node.type == "await_expression" and node.named_child_count:
            node = node.named_children[0]
        if node.type != "call_expression":
            return None
        callee = node.child_by_field_name("function")
        if callee is None:
            return None
        if callee.type == "import" or (
            callee.type == "identifier" and cls._text(callee, content) == "require"
        ):
            return cls._first_string_argument(node, content)
        return None

    @classmethod
    def _first_string_argument(cls, call: "Node", content: bytes) -> str | None:
        arguments = call.child_by_field_name("arguments")
        if arguments is None:
            return None
        for child in arguments.children:
            if child.type == "string":
                return cls._string_value(child, content)
        return None

    @staticmethod
    def _string_value(node: "Node", content: bytes) -> str:
        for child in node.children:
            if child.type == "string_fragment":
                return content[child.start_byte : child.end_byte].decode("utf-8", "replace")
        raw = content[node.start_byte : node.end_byte].decode("utf-8", "replace")
        return raw.strip("\"'`")

    # -- top-level declarations --------------------------------------

    @classmethod
    def _top_level_declarations(cls, root: "Node", content: bytes) -> list[tuple["Node", str, str]]:
        """`(node, name, kind)` for every top-level declaration we emit, with
        `export` wrappers unwrapped. `kind` is `function` or a
        `_TYPE_DECL_KINDS` value; the node is the declaration itself.
        """
        declarations: list[tuple[Node, str, str]] = []
        for child in root.children:
            node = child
            if child.type == "export_statement":
                inner = child.child_by_field_name("declaration")
                if inner is None:
                    continue
                node = inner

            if node.type in _FUNCTION_DECL_TYPES:
                name_node = node.child_by_field_name("name")
                if name_node is not None:
                    declarations.append((node, cls._text(name_node, content), "function"))
            elif node.type in _TYPE_DECL_KINDS:
                name_node = node.child_by_field_name("name") or next(
                    (kid for kid in node.children if kid.type in ("identifier", "type_identifier")),
                    None,
                )
                if name_node is not None:
                    declarations.append(
                        (node, cls._text(name_node, content), _TYPE_DECL_KINDS[node.type])
                    )
            elif node.type in ("lexical_declaration", "variable_declaration"):
                for declarator in node.children:
                    if declarator.type != "variable_declarator":
                        continue
                    value = declarator.child_by_field_name("value")
                    name_node = declarator.child_by_field_name("name")
                    if (
                        value is not None
                        and name_node is not None
                        and name_node.type == "identifier"
                        and value.type in _FUNCTION_VALUE_TYPES
                    ):
                        declarations.append((value, cls._text(name_node, content), "function"))
        return declarations

    # -- function / method entities --------------------------------

    @classmethod
    def _build_function_entity(
        cls,
        node: "Node",
        content: bytes,
        *,
        path: Path,
        language: str,
        kind: str,
        parent_qualified_name: str,
        module_qualified_name: str,
        local_top_level: set[str],
        import_bindings: dict[str, str],
        class_qualified_name: str | None,
        class_method_names: set[str],
        name_override: str | None = None,
    ) -> CodeEntity:
        name = name_override or cls._declaration_name(node, content)
        qualified_name = f"{parent_qualified_name}.{name}"
        body = node.child_by_field_name("body")
        signature = cls._function_signature(node, content)
        docstring = cls._leading_jsdoc(node, content)
        embed_text = docstring or cls._function_summary(kind, name, signature, body, content)
        calls = cls._resolve_calls(
            body,
            content,
            module_qualified_name=module_qualified_name,
            local_top_level=local_top_level,
            import_bindings=import_bindings,
            class_qualified_name=class_qualified_name,
            class_method_names=class_method_names,
        )
        return CodeEntity(
            qualified_name=qualified_name,
            name=name,
            kind=kind,
            language=language,
            embed_text=embed_text,
            file_path=str(path),
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
            signature=signature or None,
            docstring=docstring,
            parent_qualified_name=parent_qualified_name,
            calls=calls,
        )

    @classmethod
    def _build_class_entities(
        cls,
        node: "Node",
        content: bytes,
        *,
        path: Path,
        language: str,
        module_qualified_name: str,
        local_top_level: set[str],
        import_bindings: dict[str, str],
    ) -> list[CodeEntity]:
        name = cls._declaration_name(node, content)
        class_qualified_name = f"{module_qualified_name}.{name}"
        body = node.child_by_field_name("body")
        method_nodes = (
            [child for child in body.children if child.type == "method_definition"] if body else []
        )
        method_names = cls._unique_method_names(method_nodes, content)

        heritage = next((child for child in node.children if child.type == "class_heritage"), None)
        signature = cls._collapse(cls._text(heritage, content)) if heritage is not None else None
        docstring = cls._leading_jsdoc(node, content)
        embed_text = docstring or cls._class_summary(name, signature, method_names)

        entities: list[CodeEntity] = [
            CodeEntity(
                qualified_name=class_qualified_name,
                name=name,
                kind="class",
                language=language,
                embed_text=embed_text,
                file_path=str(path),
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
                signature=signature,
                docstring=docstring,
                parent_qualified_name=module_qualified_name,
            )
        ]

        emitted: set[str] = set()
        for method in method_nodes:
            method_name = cls._declaration_name(method, content)
            if method_name in emitted:
                continue  # getter/setter pair, or a TS overload signature — one entity.
            emitted.add(method_name)
            entities.append(
                cls._build_function_entity(
                    method,
                    content,
                    path=path,
                    language=language,
                    kind="constructor" if method_name == "constructor" else "method",
                    parent_qualified_name=class_qualified_name,
                    module_qualified_name=module_qualified_name,
                    local_top_level=local_top_level,
                    import_bindings=import_bindings,
                    class_qualified_name=class_qualified_name,
                    class_method_names=method_names,
                    name_override=method_name,
                )
            )
        return entities

    @classmethod
    def _build_type_entity(
        cls,
        node: "Node",
        content: bytes,
        *,
        path: Path,
        language: str,
        kind: str,
        module_qualified_name: str,
    ) -> CodeEntity:
        name = cls._declaration_name(node, content)
        qualified_name = f"{module_qualified_name}.{name}"
        body = node.child_by_field_name("body")
        name_node = node.child_by_field_name("name")

        if kind == "type":
            value = node.child_by_field_name("value")
            signature = cls._collapse(cls._text(value, content)) if value is not None else None
            embed_text = f"type {name} = {signature}" if signature else f"type {name}"
        elif kind == "enum":
            members = cls._member_names(body, content, ("property_identifier",))
            signature = None
            embed_text = f"enum {name}"
            if members:
                embed_text += f". Members: {', '.join(members)}"
        else:  # interface
            if name_node is not None and body is not None:
                between = content[name_node.end_byte : body.start_byte].decode("utf-8", "replace")
                signature = cls._collapse(between) or None
            else:
                signature = None
            members = cls._member_names(body, content, ("method_signature", "property_signature"))
            embed_text = f"interface {name}"
            if signature:
                embed_text += f" {signature}"
            if members:
                embed_text += f". Members: {', '.join(members)}"

        docstring = cls._leading_jsdoc(node, content)
        return CodeEntity(
            qualified_name=qualified_name,
            name=name,
            kind=kind,
            language=language,
            embed_text=docstring or embed_text,
            file_path=str(path),
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
            signature=signature,
            docstring=docstring,
            parent_qualified_name=module_qualified_name,
        )

    # -- names / signatures ---------------------------------------

    @staticmethod
    def _text(node: "Node", content: bytes) -> str:
        return content[node.start_byte : node.end_byte].decode("utf-8", "replace")

    @staticmethod
    def _collapse(text: str) -> str:
        return _WHITESPACE_RE.sub(" ", text).strip()

    @classmethod
    def _declaration_name(cls, node: "Node", content: bytes) -> str:
        name_node = node.child_by_field_name("name")
        if name_node is not None:
            return cls._text(name_node, content)
        for child in node.children:
            if child.type in ("identifier", "type_identifier", "property_identifier"):
                return cls._text(child, content)
        return "<anonymous>"

    @classmethod
    def _unique_method_names(cls, method_nodes: list["Node"], content: bytes) -> set[str]:
        return {cls._declaration_name(method, content) for method in method_nodes}

    @classmethod
    def _member_names(
        cls, body: "Node | None", content: bytes, member_types: tuple[str, ...]
    ) -> list[str]:
        if body is None:
            return []
        names: list[str] = []
        for child in body.children:
            if child.type not in member_types:
                continue
            if child.type == "property_identifier":
                names.append(cls._text(child, content))
                continue
            name_node = child.child_by_field_name("name") or next(
                (kid for kid in child.children if kid.type == "property_identifier"), None
            )
            if name_node is not None:
                names.append(cls._text(name_node, content))
        return names

    @classmethod
    def _function_signature(cls, node: "Node", content: bytes) -> str:
        parameters = node.child_by_field_name("parameters")
        params_text = (
            cls._collapse(cls._text(parameters, content)) if parameters is not None else "()"
        )
        return_type = node.child_by_field_name("return_type") or next(
            (child for child in node.children if child.type == "type_annotation"), None
        )
        return_text = (
            cls._collapse(cls._text(return_type, content)) if return_type is not None else ""
        )
        prefix = ""
        if any(child.type == "async" for child in node.children):
            prefix += "async "
        if node.type == "generator_function_declaration" or any(
            child.type == "*" for child in node.children
        ):
            prefix += "*"
        return f"{prefix}{params_text}{return_text}".strip()

    # A JSDoc block sits before the outermost statement — climb out of the
    # `export` / `const … =` wrappers an arrow-const declaration nests under.
    _JSDOC_WRAPPERS = {
        "export_statement",
        "lexical_declaration",
        "variable_declaration",
        "variable_declarator",
    }

    @classmethod
    def _leading_jsdoc(cls, node: "Node", content: bytes) -> str | None:
        target = node
        while target.parent is not None and target.parent.type in cls._JSDOC_WRAPPERS:
            target = target.parent
        sibling = target.prev_named_sibling
        if sibling is None or sibling.type != "comment":
            return None
        return cls._parse_jsdoc_comment(cls._text(sibling, content))

    @staticmethod
    def _parse_jsdoc_comment(raw: str) -> str | None:
        """The leading description of a `/** … */` block — lines up to the
        first `@tag`, `*` gutter stripped. Non-JSDoc `/* … */` yields None.
        """
        if not raw.startswith("/**"):
            return None
        inner = raw[3:]
        inner = inner[:-2] if inner.endswith("*/") else inner
        description: list[str] = []
        for line in inner.splitlines():
            stripped = line.strip().lstrip("*").strip()
            if stripped.startswith("@"):
                break
            if stripped:
                description.append(stripped)
        return " ".join(description) or None

    # -- summaries ----------------------------------------------

    @staticmethod
    def _module_summary(module_qualified_name: str, local_top_level: set[str]) -> str:
        if local_top_level:
            return f"Module {module_qualified_name}. Defines: {', '.join(sorted(local_top_level))}"
        return f"Module {module_qualified_name}"

    @staticmethod
    def _class_summary(name: str, signature: str | None, method_names: set[str]) -> str:
        summary = f"class {name} {signature}".strip() if signature else f"class {name}"
        if method_names:
            summary += f". Methods: {', '.join(sorted(method_names))}"
        return summary

    @classmethod
    def _function_summary(
        cls, kind: str, name: str, signature: str, body: "Node | None", content: bytes
    ) -> str:
        summary = f"{kind} {name}{signature}"
        if body is None:
            return summary
        statement = next((child for child in body.children if child.is_named), None)
        if statement is None:
            return summary
        first_line = cls._collapse(cls._text(statement, content)).splitlines()[0]
        return f"{summary}: {first_line}" if first_line else summary

    # -- calls ------------------------------------------------

    @classmethod
    def _resolve_calls(
        cls,
        body: "Node | None",
        content: bytes,
        *,
        module_qualified_name: str,
        local_top_level: set[str],
        import_bindings: dict[str, str],
        class_qualified_name: str | None,
        class_method_names: set[str],
    ) -> list[str]:
        if body is None:
            return []
        resolved: dict[str, None] = {}
        for node in cls._descendants(body):
            if node.type != "call_expression":
                continue
            callee = node.child_by_field_name("function")
            if callee is None:
                continue

            if callee.type == "identifier":
                name = cls._text(callee, content)
                if name in local_top_level:
                    resolved[f"{module_qualified_name}.{name}"] = None
                elif name in import_bindings:
                    resolved[import_bindings[name]] = None
            elif callee.type == "member_expression":
                receiver = callee.child_by_field_name("object")
                property_node = callee.child_by_field_name("property")
                if receiver is None or property_node is None:
                    continue
                member = cls._text(property_node, content)
                if (
                    receiver.type == "this"
                    and class_qualified_name is not None
                    and member in class_method_names
                ):
                    resolved[f"{class_qualified_name}.{member}"] = None
                elif receiver.type == "identifier":
                    base = cls._text(receiver, content)
                    if base in import_bindings:
                        resolved[f"{import_bindings[base]}.{member}"] = None
        return list(resolved)

    @classmethod
    def _descendants(cls, node: "Node"):
        for child in node.children:
            yield child
            yield from cls._descendants(child)
