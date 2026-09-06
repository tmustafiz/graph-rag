import hashlib
import logging
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from ..models import Chunk, ParsedDocument, Section, Source

if TYPE_CHECKING:
    from tree_sitter import Node

logger = logging.getLogger(__name__)

_WHITESPACE_RE = re.compile(r"\s+")
_SUFFIXES = {".css", ".scss", ".sass", ".less"}
# `.sass` (indented syntax) has no dedicated grammar — the `scss` grammar
# handles it best-effort.
_GRAMMAR_BY_SUFFIX = {".scss": "scss", ".sass": "scss", ".less": "less"}
_IMPORT_NODE_TYPES = {"import_statement", "use_statement", "forward_statement"}
_NESTED_CONTAINER_TYPES = {"media_statement", "supports_statement"}
# `@use "sass:math"` and friends are Sass built-ins, not files.
_BUILTIN_IMPORT_RE = re.compile(r"^(?:sass:|https?://|//|/)")


class StylesheetParser:
    """Parses `.css` / `.scss` / `.sass` / `.less` into a `Source` + one
    `Section` per file (plus one per top-level `@media` / `@supports`) and a
    `Chunk` per rule, so the plain `search` tool covers stylesheet content.

    SCSS nesting is flattened into full selector paths (`.card .title`,
    `.card:hover`). Custom properties (`--x`), SCSS `$variables`, `@mixin`s and
    `%placeholder`s each also get their own small name-bearing chunk so
    "where is `--accent` defined" is answerable. `@import` / `@use` /
    `@forward` resolve to `(Source)-[:IMPORTS]->(Source)` edges.

    No `CodeEntity` — CSS has no call graph.
    """

    @staticmethod
    def can_handle(path: Path) -> bool:
        return path.suffix.lower() in _SUFFIXES

    def parse(self, path: Path) -> ParsedDocument:
        try:
            from tree_sitter_language_pack import get_parser
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "Parsing stylesheets needs the optional 'css' extra. Install it with "
                "`pip install 'grag-mcp[css]'` (or `uv sync --extra css`)."
            ) from exc

        content = path.read_bytes()
        suffix = path.suffix.lower()
        source = Source(
            path=str(path),
            source_type=suffix.lstrip("."),
            content_hash=hashlib.sha256(content).hexdigest(),
            ingested_at=datetime.now(UTC),
        )

        grammar = _GRAMMAR_BY_SUFFIX.get(suffix, "css")
        root = get_parser(grammar).parse(content).root_node
        if root.has_error:
            logger.warning(
                "tree-sitter reported syntax errors in %s; ingesting the partially-parsed result",
                path,
            )

        builder = _StylesheetBuilder(source_path=str(path), content=content)
        builder.consume(root)

        return ParsedDocument(
            source=source,
            sections=builder.sections,
            chunks=builder.chunks,
            source_imports=_resolve_imports(builder.raw_imports, path, suffix),
        )


class _StylesheetBuilder:
    """Walks a stylesheet CST into `Section`s + `Chunk`s."""

    def __init__(self, *, source_path: str, content: bytes) -> None:
        self._source_path = source_path
        self._content = content
        self._section_count = 0
        self._orders: dict[str, int] = {}
        self.sections: list[Section] = []
        self.chunks: list[Chunk] = []
        self.raw_imports: list[str] = []
        self._root_section = self._new_section(Path(source_path).name, level=1, parent=None)

    def consume(self, root: "Node") -> None:
        self._walk(root, section=self._root_section, parent_selectors=[])

    # -- tree walk ----------------------------------------------------

    def _walk(self, node: "Node", *, section: Section, parent_selectors: list[str]) -> None:
        for child in node.children:
            if child.type in _IMPORT_NODE_TYPES:
                value = _string_literal(child, self._content)
                if value:
                    self.raw_imports.append(value)
            elif child.type == "rule_set":
                self._emit_rule(child, section=section, parent_selectors=parent_selectors)
            elif child.type in _NESTED_CONTAINER_TYPES and not parent_selectors:
                nested = self._new_section(
                    _collapse(_prelude_text(child, self._content)),
                    level=2,
                    parent=self._root_section,
                )
                block = _first_child(child, "block")
                if block is not None:
                    self._walk(block, section=nested, parent_selectors=[])
            elif child.type in _NESTED_CONTAINER_TYPES:
                block = _first_child(child, "block")
                if block is not None:
                    self._walk(block, section=section, parent_selectors=parent_selectors)
            elif child.type == "mixin_statement":
                self._emit_mixin(child, section=section)
            elif child.type == "declaration" and not parent_selectors:
                # A top-level declaration is an SCSS/Less `$var` (or `--x`);
                # declarations inside a rule block are emitted by `_emit_rule`.
                self._emit_token_declaration(child, section=section, context=None)

    def _emit_rule(self, node: "Node", *, section: Section, parent_selectors: list[str]) -> None:
        selectors_node = _first_child(node, "selectors")
        own = _selector_list(selectors_node, self._content) if selectors_node else []
        flattened = _flatten_selectors(parent_selectors, own)
        block = _first_child(node, "block")
        declarations = (
            [c for c in block.children if c.type == "declaration"] if block is not None else []
        )
        declaration_texts = [_collapse(_text(d, self._content)).rstrip(";") for d in declarations]

        selector_label = (
            ", ".join(flattened)
            if flattened
            else _collapse(_text(selectors_node, self._content) if selectors_node else "&")
        )
        body = "; ".join(declaration_texts)
        rule_text = f"{selector_label} {{ {body} }}" if body else f"{selector_label} {{ }}"
        self._add_chunk(rule_text, section)

        for declaration in declarations:
            self._emit_token_declaration(declaration, section=section, context=selector_label)

        if block is not None:
            self._walk(block, section=section, parent_selectors=flattened)

    def _emit_token_declaration(
        self, node: "Node", *, section: Section, context: str | None
    ) -> None:
        property_node = _first_child(node, "property_name")
        if property_node is None:
            return
        name = _text(property_node, self._content)
        if not (name.startswith("--") or name.startswith("$")):
            return
        text = _collapse(_text(node, self._content))
        if context:
            text = f"{text}  (in {context})"
        self._add_chunk(text, section)

    def _emit_mixin(self, node: "Node", *, section: Section) -> None:
        name_node = _first_child(node, "identifier")
        parameters = _first_child(node, "parameters")
        name = _text(name_node, self._content) if name_node else "?"
        params = _collapse(_text(parameters, self._content)) if parameters else "()"
        self._add_chunk(f"@mixin {name}{params}", section)

    # -- section / chunk builders --------------------------------

    def _new_section(self, title: str, *, level: int, parent: Section | None) -> Section:
        index = self._section_count
        self._section_count += 1
        section = Section(
            id=f"{self._source_path}::s{index:04d}",
            title=title or "(stylesheet)",
            level=level,
            breadcrumb=f"{parent.breadcrumb} > {title}" if parent else (title or "(stylesheet)"),
            order=index,
            parent_id=parent.id if parent else None,
        )
        self.sections.append(section)
        return section

    def _add_chunk(self, text: str, section: Section) -> None:
        order = self._orders.get(section.id, 0)
        self._orders[section.id] = order + 1
        self.chunks.append(
            Chunk(
                id=f"{section.id}::c{order:04d}",
                section_id=section.id,
                order=order,
                text=text,
                token_count=len(text.split()),
                content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            )
        )


# -- module-level helpers ----------------------------------------------


def _text(node: "Node | None", content: bytes) -> str:
    if node is None:
        return ""
    return content[node.start_byte : node.end_byte].decode("utf-8", "replace")


def _collapse(text: str) -> str:
    return _WHITESPACE_RE.sub(" ", text).strip()


def _first_child(node: "Node", type_name: str) -> "Node | None":
    field = node.child_by_field_name(type_name)
    if field is not None:
        return field
    return next((child for child in node.children if child.type == type_name), None)


def _string_literal(node: "Node", content: bytes) -> str | None:
    string_node = next(
        (child for child in node.children if child.type in ("string_value", "string")), None
    )
    if string_node is None:
        return None
    inner = next((child for child in string_node.children if child.type == "string_content"), None)
    if inner is not None:
        return _text(inner, content) or None
    return _text(string_node, content).strip("\"'") or None


def _prelude_text(node: "Node", content: bytes) -> str:
    block = _first_child(node, "block")
    end = block.start_byte if block is not None else node.end_byte
    return _text_range(content, node.start_byte, end)


def _text_range(content: bytes, start: int, end: int) -> str:
    return content[start:end].decode("utf-8", "replace")


def _selector_list(selectors_node: "Node | None", content: bytes) -> list[str]:
    if selectors_node is None:
        return []
    parts = [
        _collapse(_text(child, content)) for child in selectors_node.children if child.is_named
    ]
    return [part for part in parts if part]


def _flatten_selectors(parents: list[str], own: list[str]) -> list[str]:
    if not parents:
        return own or []
    if not own:
        return parents
    combined: list[str] = []
    for parent in parents:
        for selector in own:
            if "&" in selector:
                combined.append(selector.replace("&", parent))
            else:
                combined.append(f"{parent} {selector}")
    return combined


def _resolve_imports(raw_imports: list[str], path: Path, suffix: str) -> list[str]:
    resolved: dict[str, None] = {}
    base = path.parent
    for raw in raw_imports:
        target = raw.strip()
        if not target or _BUILTIN_IMPORT_RE.match(target):
            continue
        target = target.split("?", 1)[0].split("#", 1)[0]
        candidate = _resolve_one(base, target, suffix)
        resolved.setdefault(candidate, None)
    return list(resolved)


def _resolve_one(base: Path, target: str, suffix: str) -> str:
    raw = (base / target).resolve()
    stem_variants = [raw]
    if not raw.suffix:
        extensions = {
            ".scss": (".scss", ".sass", ".css"),
            ".sass": (".sass", ".scss", ".css"),
            ".less": (".less", ".css"),
            ".css": (".css",),
        }.get(suffix, (suffix,))
        for extension in extensions:
            stem_variants.append(raw.with_name(raw.name + extension))
            stem_variants.append(raw.with_name(f"_{raw.name}{extension}"))
    for variant in stem_variants:
        if variant.is_file():
            return str(variant)
    return str(stem_variants[1] if len(stem_variants) > 1 else raw)
