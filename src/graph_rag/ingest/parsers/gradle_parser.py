import hashlib
import logging
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from ..models import ExternalArtifact, Module, ModuleDependency, ParsedDocument, Source

if TYPE_CHECKING:
    from tree_sitter import Node

logger = logging.getLogger(__name__)

_SETTINGS_NAMES = ("settings.gradle", "settings.gradle.kts")
_BUILD_NAMES = ("build.gradle", "build.gradle.kts")
_DEFAULT_SOURCE_DIRS = ("src/main/java", "src/test/java")
_GENERATED_SOURCE_DIRS = ("build/generated", "build/generated-sources")
# Dependency configurations we lift a coordinate from (exact or `<x>Implementation` / `<x>Api` …).
_CONFIG_EXACT = {
    "implementation",
    "api",
    "compileOnly",
    "runtimeOnly",
    "compile",
    "runtime",
    "annotationProcessor",
    "kapt",
    "developmentOnly",
    "testImplementation",
    "testCompileOnly",
    "testRuntimeOnly",
}
_CONFIG_SUFFIXES = ("Implementation", "Api", "CompileOnly", "RuntimeOnly", "AnnotationProcessor")
_COORDINATE = re.compile(r"^[\w.\-]+:[\w.\-]+(?::[\w.\-${}]+)?$")
_SRC_DIR_CALLS = ("srcDir", "srcDirs")
_STRING_NODE_TYPES = ("string", "string_literal", "line_string_literal")
# Groovy tags a nested call `end_command`; Kotlin uses `call_expression`.
_CALL_NODE_TYPES = ("command", "end_command", "func", "call_expression")
_ASSIGN_NODE_TYPES = ("assignment", "command", "end_command")
# Blocks that configure *other* modules, not this file's. The parse is
# per-file and flat, so a root `build.gradle`'s `subprojects { dependencies
# { ... } }` would otherwise be attributed to the root module; skip the
# subtree and let each subproject's own build file contribute its deps.
_FOREIGN_SCOPE_BLOCKS = ("subprojects", "allprojects")


class GradleParser:
    """Best-effort parse of `build.gradle` / `build.gradle.kts` /
    `settings.gradle(.kts)` into one `Module` plus its declared dependencies.

    Uses the tree-sitter `groovy` / `kotlin` grammars (from the language pack).
    Extraction is deliberately shallow — every call and `name = "value"`
    assignment in the file, block nesting ignored: `group` / `version`,
    `rootProject.name`, `include ':a', ':b'`, `dependencies { implementation
    'g:a:v' }` (configuration → `scope`), `project(':x')` dependencies, and
    `srcDir(s)` entries. `subprojects` / `allprojects` blocks are skipped
    (their contents configure other modules). Dynamic configuration is
    skipped. A grammar gap or a missing language pack logs a warning and
    yields whatever was found.
    """

    @staticmethod
    def can_handle(path: Path) -> bool:
        return path.name in (*_SETTINGS_NAMES, *_BUILD_NAMES)

    def parse(self, path: Path) -> ParsedDocument:
        content = path.read_bytes()
        source = Source(
            path=str(path),
            source_type="gradle",
            content_hash=hashlib.sha256(content).hexdigest(),
            ingested_at=datetime.now(UTC),
        )
        module_dir = path.parent.resolve()
        language = "kotlin" if path.name.endswith(".kts") else "groovy"

        try:
            from tree_sitter_language_pack import get_parser

            root = get_parser(language).parse(content).root_node
        except (ModuleNotFoundError, LookupError) as exc:
            logger.warning("cannot parse %s (%s grammar unavailable): %s", path, language, exc)
            return ParsedDocument(source=source)

        calls: list[tuple[str, list[str]]] = []
        assignments: dict[str, str] = {}
        self._collect(root, content, calls, assignments)

        root_name = assignments.get("rootProject.name") or assignments.get("name")
        module = Module(
            path=str(module_dir),
            artifact=root_name or module_dir.name,
            group=assignments.get("group") or self._call_value(calls, "group"),
            version=assignments.get("version") or self._call_value(calls, "version"),
            build_tool="gradle",
            packages=[],
            source_roots=self._source_roots(calls, module_dir),
        )
        if module.group:
            module.packages = [module.group]

        externals: dict[str, ExternalArtifact] = {}
        dependencies: list[ModuleDependency] = []
        for name, args in calls:
            self._handle_dependency_call(name, args, module.path, externals, dependencies)
        for included in self._included_projects(calls):
            child_dir = (module_dir / included).resolve()
            dependencies.append(
                ModuleDependency(
                    module_path=module.path, target_path=str(child_dir), scope="reactor"
                )
            )

        return ParsedDocument(
            source=source,
            modules=[module],
            external_artifacts=list(externals.values()),
            module_dependencies=dependencies,
        )

    # -- interpretation --

    @classmethod
    def _handle_dependency_call(
        cls,
        name: str,
        args: list[str],
        module_path: str,
        externals: dict[str, ExternalArtifact],
        dependencies: list[ModuleDependency],
    ) -> None:
        if not cls._is_config(name):
            return
        for arg in args:
            if arg.startswith("project:"):
                dependencies.append(
                    ModuleDependency(module_path=module_path, target_gav=arg, scope=name)
                )
            elif _COORDINATE.match(arg):
                group, artifact, *rest = arg.split(":")
                gav = f"{group}:{artifact}"
                externals.setdefault(
                    gav,
                    ExternalArtifact(
                        gav=gav, group=group, artifact=artifact, version=rest[0] if rest else None
                    ),
                )
                dependencies.append(
                    ModuleDependency(module_path=module_path, target_gav=gav, scope=name)
                )

    @staticmethod
    def _is_config(name: str) -> bool:
        return name in _CONFIG_EXACT or name.endswith(_CONFIG_SUFFIXES)

    @staticmethod
    def _included_projects(calls: list[tuple[str, list[str]]]) -> list[str]:
        included: list[str] = []
        for name, args in calls:
            if name != "include":
                continue
            for arg in args:
                relative = arg.lstrip(":").replace(":", "/")
                if relative and relative not in included:
                    included.append(relative)
        return included

    @staticmethod
    def _call_value(calls: list[tuple[str, list[str]]], name: str) -> str | None:
        return next((args[0] for call_name, args in calls if call_name == name and args), None)

    @classmethod
    def _source_roots(cls, calls: list[tuple[str, list[str]]], module_dir: Path) -> list[str]:
        relative = list(_DEFAULT_SOURCE_DIRS)
        for name, args in calls:
            if name in _SRC_DIR_CALLS:
                relative.extend(args)
        candidates = [module_dir / rel for rel in relative]
        candidates.extend(
            module_dir / generated
            for generated in _GENERATED_SOURCE_DIRS
            if (module_dir / generated).is_dir()
        )
        ordered: list[str] = []
        for candidate in candidates:
            resolved = str(candidate.resolve())
            if resolved not in ordered:
                ordered.append(resolved)
        return ordered

    # -- tree-sitter walk (grammar-agnostic, flat) --

    @classmethod
    def _collect(
        cls,
        node: "Node",
        content: bytes,
        calls: list[tuple[str, list[str]]],
        assignments: dict[str, str],
    ) -> None:
        if node.type in _CALL_NODE_TYPES:
            if cls._call_name(node, content) in _FOREIGN_SCOPE_BLOCKS:
                return  # don't descend — these deps belong to other modules (#126)
            parsed = cls._as_call(node, content)
            if parsed is not None:
                calls.append(parsed)
        if node.type in _ASSIGN_NODE_TYPES:
            assigned = cls._as_assignment(node, content)
            if assigned is not None:
                assignments.setdefault(*assigned)
        for child in node.children:
            cls._collect(child, content, calls, assignments)

    @classmethod
    def _as_call(cls, node: "Node", content: bytes) -> tuple[str, list[str]] | None:
        name = cls._call_name(node, content)
        if not name:
            return None
        args: list[str] = []
        for descendant in cls._iter(node):
            if descendant is node:
                continue
            if descendant.type in _CALL_NODE_TYPES:
                nested = cls._call_name(descendant, content)
                if nested == "project":
                    for string_value in cls._string_values(descendant, content):
                        args.append(f"project:{string_value.lstrip(':').replace(':', '/')}")
                break
            if descendant.type in _STRING_NODE_TYPES:
                args.append(cls._string_text(descendant, content))
        return name, args

    @classmethod
    def _as_assignment(cls, node: "Node", content: bytes) -> tuple[str, str] | None:
        has_equals = any(
            child.type in ("=", "operators") and cls._text(child, content).strip().startswith("=")
            for child in node.children
        )
        if not has_equals and node.type in ("command", "end_command"):
            return None
        lhs = next(
            (
                cls._text(child, content).strip()
                for child in node.children
                if child.type in ("unit", "directly_assignable_expression", "identifier")
            ),
            None,
        )
        strings = cls._string_values(node, content)
        if not lhs or not strings:
            return None
        return lhs.split(".")[-1] if lhs.startswith("rootProject") else lhs, strings[0]

    @classmethod
    def _call_name(cls, node: "Node", content: bytes) -> str | None:
        for child in node.children:
            if child.type in ("identifier", "simple_identifier"):
                return cls._text(child, content)
            # Groovy wraps a `name { ... }` block call as `command > block >
            # unit > identifier`; descend so block-form calls are named too.
            if child.type in ("unit", "block"):
                inner = cls._call_name(child, content)
                if inner:
                    return inner
        return None

    @classmethod
    def _string_values(cls, node: "Node", content: bytes) -> list[str]:
        return [
            cls._string_text(descendant, content)
            for descendant in cls._iter(node)
            if descendant.type in _STRING_NODE_TYPES
        ]

    @classmethod
    def _string_text(cls, node: "Node", content: bytes) -> str:
        for child in node.children:
            if child.type in ("string_content", "line_str_text"):
                return cls._text(child, content)
        return cls._text(node, content).strip("'\"")

    @staticmethod
    def _iter(node: "Node") -> list["Node"]:
        out: list[Node] = []
        stack = [node]
        while stack:
            current = stack.pop()
            out.append(current)
            stack.extend(reversed(current.children))
        return out

    @staticmethod
    def _text(node: "Node", content: bytes) -> str:
        return content[node.start_byte : node.end_byte].decode("utf-8", "replace")
