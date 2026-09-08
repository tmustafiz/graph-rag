import hashlib
import logging
from datetime import UTC, datetime
from pathlib import Path

from .graph.graph_writer import GraphWriter
from .ingest.embedders import Embedder
from .ingest.enricher import Enricher
from .ingest.models import CodeEntity, ParsedDocument, Source
from .ingest.scip import ScipDocument, ScipReader, ScipSymbol, ScipSymbolParser

logger = logging.getLogger(__name__)

# `SymbolInformation.Kind` values graph-rag maps to a `CodeEntity.kind`; anything
# else falls back to the descriptor suffix (`ScipSymbolParser`).
_SCIP_KINDS: dict[int, str] = {
    6: "class",
    7: "constant",
    9: "constructor",
    12: "enum",
    17: "field",
    21: "function",
    26: "interface",
    38: "method",
    43: "namespace",
    61: "trait",
}


class ScipIngestor:
    """Consumes a SCIP index (`grag-mcp ingest --scip`) into the same graph as
    static parsing.

    Each SCIP `Document` becomes a `ParsedDocument` whose `CodeEntity`s carry
    `resolution="scip"`; `GraphWriter`'s per-`Source` reconcile then replaces
    any static entities for that file — SCIP wins on overlap. `SymbolInformation`
    → `CodeEntity` (kind from `Kind` else the symbol descriptor);
    `Relationship(is_implementation)` → `IMPLEMENTS`,
    `Relationship(is_reference|is_type_definition)` on a type → `IMPORTS`;
    a reference `Occurrence` with an `enclosing_range` whose enclosing symbol is
    a method → `CALLS`.
    """

    def __init__(self, embedder: Embedder, writer: GraphWriter) -> None:
        self._enricher = Enricher(embedder)
        self._writer = writer

    def ingest(self, index_path: Path, root: Path | None = None, dry_run: bool = False) -> int:
        scip_documents = ScipReader.read(index_path.read_bytes())
        parsed = self._build_documents(scip_documents, root)
        if not dry_run:
            for document in parsed:
                self._writer.write(self._enricher.enrich(document))
        logger.info(
            "scip ingest: %d documents, %d code entities",
            len(parsed),
            sum(len(document.code_entities) for document in parsed),
        )
        return len(parsed)

    # -- pure build (unit-tested without an embedder / Neo4j) --

    @classmethod
    def _build_documents(
        cls, scip_documents: list[ScipDocument], root: Path | None
    ) -> list[ParsedDocument]:
        return [
            cls._build_document(scip_document, root)
            for scip_document in scip_documents
            if scip_document.relative_path
        ]

    @classmethod
    def _build_document(cls, scip_document: ScipDocument, root: Path | None) -> ParsedDocument:
        path = (
            Path(root, scip_document.relative_path) if root else Path(scip_document.relative_path)
        )
        source = Source(
            path=str(path),
            source_type=scip_document.language.lower() or "scip",
            content_hash=cls._content_hash(path, scip_document),
            ingested_at=datetime.now(UTC),
        )

        qn_by_symbol: dict[str, str] = {}
        parsed_by_symbol: dict[str, tuple[str, str, str]] = {}
        for scip_symbol in scip_document.symbols:
            parsed = ScipSymbolParser.parse(scip_symbol.symbol)
            if parsed is None:
                continue
            qn_by_symbol[scip_symbol.symbol] = parsed[0]
            parsed_by_symbol[scip_symbol.symbol] = parsed

        # method symbol → start line of its definition occurrence, for CALLS.
        def_line: dict[int, str] = {
            occurrence.range[0]: occurrence.symbol
            for occurrence in scip_document.occurrences
            if occurrence.is_definition and occurrence.range
        }
        calls_by_symbol: dict[str, list[str]] = {}
        for occurrence in scip_document.occurrences:
            if occurrence.is_definition or not occurrence.enclosing_range:
                continue
            enclosing = def_line.get(occurrence.enclosing_range[0])
            target_qn = qn_by_symbol.get(occurrence.symbol) or cls._external_qn(occurrence.symbol)
            if enclosing is None or target_qn is None:
                continue
            enclosing_kind = cls._entity_kind(
                next(
                    (s for s in scip_document.symbols if s.symbol == enclosing),
                    ScipSymbol(symbol=enclosing),
                ),
                parsed_by_symbol.get(enclosing),
            )
            if enclosing_kind in ("method", "constructor", "function"):
                calls_by_symbol.setdefault(enclosing, []).append(target_qn)

        entities = [
            cls._entity(
                scip_symbol,
                parsed_by_symbol[scip_symbol.symbol],
                qn_by_symbol,
                calls_by_symbol.get(scip_symbol.symbol, []),
                str(path),
            )
            for scip_symbol in scip_document.symbols
            if scip_symbol.symbol in parsed_by_symbol
        ]
        return ParsedDocument(source=source, code_entities=entities)

    @classmethod
    def _entity(
        cls,
        scip_symbol: ScipSymbol,
        parsed: tuple[str, str, str],
        qn_by_symbol: dict[str, str],
        calls: list[str],
        file_path: str,
    ) -> CodeEntity:
        qualified_name, _suffix_kind, name = parsed
        kind = cls._entity_kind(scip_symbol, parsed)
        docstring = "\n".join(scip_symbol.documentation).strip() or None
        implements: list[str] = []
        imports: list[str] = []
        for (
            target,
            is_reference,
            is_implementation,
            is_type_definition,
        ) in scip_symbol.relationships:
            target_qn = qn_by_symbol.get(target) or cls._external_qn(target)
            if target_qn is None:
                continue
            if is_implementation:
                implements.append(target_qn)
            elif is_reference or is_type_definition:
                imports.append(target_qn)
        parent = qualified_name.rsplit(".", 1)[0] if "." in qualified_name else None
        return CodeEntity(
            qualified_name=qualified_name,
            name=name or qualified_name.rsplit(".", 1)[-1],
            kind=kind,
            language="java" if "scip-java" in scip_symbol.symbol else "scip",
            embed_text=docstring or f"{kind} {qualified_name}",
            file_path=file_path,
            docstring=docstring,
            parent_qualified_name=parent if parent in qn_by_symbol.values() else None,
            calls=_dedupe(calls),
            imports=_dedupe(imports),
            implements_types=_dedupe(implements),
            resolution="scip",
        )

    @staticmethod
    def _entity_kind(scip_symbol: ScipSymbol, parsed: tuple[str, str, str] | None) -> str:
        mapped = _SCIP_KINDS.get(scip_symbol.kind)
        if mapped:
            return mapped
        suffix_kind = parsed[1] if parsed else "symbol"
        return {"type": "class", "term": "field", "namespace": "namespace"}.get(
            suffix_kind, suffix_kind
        )

    @staticmethod
    def _external_qn(symbol: str) -> str | None:
        parsed = ScipSymbolParser.parse(symbol)
        return parsed[0] if parsed else None

    @staticmethod
    def _content_hash(path: Path, scip_document: ScipDocument) -> str:
        try:
            return hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            seed = (scip_document.relative_path + "|scip").encode("utf-8")
            return hashlib.sha256(seed).hexdigest()


def _dedupe(items: list[str]) -> list[str]:
    seen: dict[str, None] = {}
    for item in items:
        if item:
            seen.setdefault(item, None)
    return list(seen)
