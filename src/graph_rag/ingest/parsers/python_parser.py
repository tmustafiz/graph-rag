import ast
import hashlib
from datetime import UTC, datetime
from pathlib import Path

from ..models import CodeEntity, ParsedDocument, Source

_DefNode = ast.FunctionDef | ast.AsyncFunctionDef


class PythonParser:
    """Parses a Python module into a `Source` + `CodeEntity` list, using `ast`.

    Modules, classes, and functions/methods become `CodeEntity` nodes
    (structural chunking, not prose) with best-effort, purely static
    `calls`/`imports` edges — no type resolution, so attribute calls on
    arbitrary objects (not `self.*` or a known imported module) are skipped
    rather than guessed.
    """

    def parse(self, path: Path) -> ParsedDocument:
        content = path.read_bytes()
        source = Source(
            path=str(path),
            source_type="python",
            content_hash=hashlib.sha256(content).hexdigest(),
            ingested_at=datetime.now(UTC),
        )

        text = content.decode("utf-8")
        tree = ast.parse(text, filename=str(path))
        module_qualified_name = self._module_qualified_name(path)
        is_package = path.stem == "__init__"
        imports, module_aliases, from_aliases = self._collect_imports(
            tree, module_qualified_name, is_package
        )

        top_level_defs = [
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)
        ]
        local_top_level = {node.name for node in top_level_defs}

        module_docstring = ast.get_docstring(tree)
        module_embed_text = module_docstring or self._module_summary(
            module_qualified_name, local_top_level
        )
        entities: list[CodeEntity] = [
            CodeEntity(
                qualified_name=module_qualified_name,
                name=module_qualified_name.rsplit(".", 1)[-1],
                kind="module",
                embed_text=module_embed_text,
                file_path=str(path),
                start_line=1,
                end_line=len(text.splitlines()) or 1,
                docstring=module_docstring,
                imports=imports,
            )
        ]

        for node in top_level_defs:
            if isinstance(node, ast.ClassDef):
                entities.extend(
                    self._build_class_entities(
                        node,
                        path,
                        module_qualified_name,
                        local_top_level,
                        module_aliases,
                        from_aliases,
                    )
                )
            else:
                entities.append(
                    self._build_function_entity(
                        node,
                        module_qualified_name,
                        path=path,
                        parent_qualified_name=module_qualified_name,
                        kind="function",
                        local_top_level=local_top_level,
                        enclosing_class=None,
                        class_method_names=set(),
                        module_aliases=module_aliases,
                        from_aliases=from_aliases,
                    )
                )

        return ParsedDocument(source=source, code_entities=entities)

    @staticmethod
    def _module_qualified_name(path: Path) -> str:
        resolved = path.resolve()
        parts: list[str] = [] if resolved.stem == "__init__" else [resolved.stem]
        current = resolved.parent
        while (current / "__init__.py").exists():
            parts.append(current.name)
            current = current.parent
        parts.reverse()
        return ".".join(parts)

    @staticmethod
    def _resolve_relative_module(
        module_qualified_name: str, is_package: bool, level: int, module: str | None
    ) -> str:
        if is_package:
            containing_package = module_qualified_name
        elif "." in module_qualified_name:
            containing_package = module_qualified_name.rsplit(".", 1)[0]
        else:
            containing_package = ""
        package_parts = containing_package.split(".") if containing_package else []
        trim = level - 1
        base_parts = package_parts[: len(package_parts) - trim] if trim > 0 else package_parts
        base = ".".join(base_parts)
        return f"{base}.{module}" if module else base

    @staticmethod
    def _collect_imports(
        tree: ast.Module, module_qualified_name: str, is_package: bool
    ) -> tuple[list[str], dict[str, str], dict[str, str]]:
        imports: list[str] = []
        module_aliases: dict[str, str] = {}
        from_aliases: dict[str, str] = {}
        for node in tree.body:
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(alias.name)
                    if alias.asname:
                        module_aliases[alias.asname] = alias.name
                    elif "." not in alias.name:
                        module_aliases[alias.name] = alias.name
            elif isinstance(node, ast.ImportFrom):
                if node.level == 0:
                    base = node.module or ""
                else:
                    base = PythonParser._resolve_relative_module(
                        module_qualified_name, is_package, node.level, node.module
                    )
                for alias in node.names:
                    if alias.name == "*":
                        continue
                    symbol = f"{base}.{alias.name}" if base else alias.name
                    imports.append(symbol)
                    from_aliases[alias.asname or alias.name] = symbol
        return imports, module_aliases, from_aliases

    @staticmethod
    def _build_class_entities(
        node: ast.ClassDef,
        path: Path,
        module_qualified_name: str,
        local_top_level: set[str],
        module_aliases: dict[str, str],
        from_aliases: dict[str, str],
    ) -> list[CodeEntity]:
        class_qualified_name = f"{module_qualified_name}.{node.name}"
        method_nodes = [
            child
            for child in node.body
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef)
        ]
        class_method_names = {method.name for method in method_nodes}

        bases = ", ".join(ast.unparse(base) for base in node.bases)
        signature = f"({bases})" if bases else None
        docstring = ast.get_docstring(node)
        embed_text = docstring or PythonParser._class_summary(node.name, signature, method_nodes)

        entities: list[CodeEntity] = [
            CodeEntity(
                qualified_name=class_qualified_name,
                name=node.name,
                kind="class",
                embed_text=embed_text,
                file_path=str(path),
                start_line=node.lineno,
                end_line=node.end_lineno or node.lineno,
                signature=signature,
                docstring=docstring,
                parent_qualified_name=module_qualified_name,
            )
        ]
        for method_node in method_nodes:
            entities.append(
                PythonParser._build_function_entity(
                    method_node,
                    module_qualified_name,
                    path=path,
                    parent_qualified_name=class_qualified_name,
                    kind="method",
                    local_top_level=local_top_level,
                    enclosing_class=class_qualified_name,
                    class_method_names=class_method_names,
                    module_aliases=module_aliases,
                    from_aliases=from_aliases,
                )
            )
        return entities

    @staticmethod
    def _build_function_entity(
        node: _DefNode,
        module_qualified_name: str,
        *,
        path: Path,
        parent_qualified_name: str,
        kind: str,
        local_top_level: set[str],
        enclosing_class: str | None,
        class_method_names: set[str],
        module_aliases: dict[str, str],
        from_aliases: dict[str, str],
    ) -> CodeEntity:
        qualified_name = f"{parent_qualified_name}.{node.name}"
        returns = f" -> {ast.unparse(node.returns)}" if node.returns else ""
        signature = f"({ast.unparse(node.args)}){returns}"
        docstring = ast.get_docstring(node)
        embed_text = docstring or PythonParser._function_summary(
            kind, node.name, signature, node.body
        )
        calls = PythonParser._resolve_calls(
            node,
            module_qualified_name,
            local_top_level,
            enclosing_class,
            class_method_names,
            module_aliases,
            from_aliases,
        )
        return CodeEntity(
            qualified_name=qualified_name,
            name=node.name,
            kind=kind,
            embed_text=embed_text,
            file_path=str(path),
            start_line=node.lineno,
            end_line=node.end_lineno or node.lineno,
            signature=signature,
            docstring=docstring,
            parent_qualified_name=parent_qualified_name,
            calls=calls,
        )

    @staticmethod
    def _resolve_calls(
        node: _DefNode,
        module_qualified_name: str,
        local_top_level: set[str],
        enclosing_class: str | None,
        class_method_names: set[str],
        module_aliases: dict[str, str],
        from_aliases: dict[str, str],
    ) -> list[str]:
        resolved: dict[str, None] = {}
        for call in ast.walk(node):
            if not isinstance(call, ast.Call):
                continue
            func = call.func
            if isinstance(func, ast.Name):
                if func.id in local_top_level:
                    resolved[f"{module_qualified_name}.{func.id}"] = None
                elif func.id in from_aliases:
                    resolved[from_aliases[func.id]] = None
            elif isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
                base = func.value.id
                if base == "self" and enclosing_class and func.attr in class_method_names:
                    resolved[f"{enclosing_class}.{func.attr}"] = None
                elif base in module_aliases:
                    resolved[f"{module_aliases[base]}.{func.attr}"] = None
        return list(resolved)

    @staticmethod
    def _first_body_line(body: list[ast.stmt]) -> str:
        if not body:
            return ""
        return ast.unparse(body[0]).splitlines()[0]

    @staticmethod
    def _function_summary(kind: str, name: str, signature: str, body: list[ast.stmt]) -> str:
        first_line = PythonParser._first_body_line(body)
        summary = f"{kind} {name}{signature}"
        return f"{summary}: {first_line}" if first_line else summary

    @staticmethod
    def _class_summary(name: str, signature: str | None, method_nodes: list[_DefNode]) -> str:
        method_names = ", ".join(method.name for method in method_nodes)
        summary = f"class {name}{signature or ''}"
        return f"{summary}. Methods: {method_names}" if method_names else summary

    @staticmethod
    def _module_summary(module_qualified_name: str, local_top_level: set[str]) -> str:
        if local_top_level:
            return f"Module {module_qualified_name}. Defines: {', '.join(sorted(local_top_level))}"
        return f"Module {module_qualified_name}"
