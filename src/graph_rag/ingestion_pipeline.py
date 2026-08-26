import hashlib
import logging
from pathlib import Path

from .graph.graph_writer import GraphWriter
from .ingest.embedders import Embedder
from .ingest.enricher import Enricher
from .ingest.parser import Parser
from .ingest.parser_registry import ParserRegistry
from .ingestion_result import IngestionResult
from .unsupported_file_type_error import UnsupportedFileTypeError

logger = logging.getLogger(__name__)


class IngestionPipeline:
    """Parses, embeds, and upserts a file or directory (recursive) into the graph.

    Skips any file whose content hash matches what's already stored for its
    `Source` (no re-parse, no re-embedding). `dry_run=True` parses to report
    what would change without generating embeddings or writing to Neo4j. A
    file that fails to parse/embed/write is recorded as an `IngestionResult`
    with `error` set, rather than aborting the rest of the batch.
    """

    def __init__(self, registry: ParserRegistry, embedder: Embedder, writer: GraphWriter) -> None:
        self._registry = registry
        self._enricher = Enricher(embedder)
        self._writer = writer

    def run(self, path: Path, dry_run: bool = False) -> list[IngestionResult]:
        logger.info("ingestion run starting: path=%s dry_run=%s", path, dry_run)

        if path.is_file():
            parser = self._registry.for_path(path)
            if parser is None:
                raise UnsupportedFileTypeError(path)
            results = [self._ingest_one(path, parser, dry_run)]
        else:
            pairs = sorted(
                (
                    (file, self._registry.for_path(file))
                    for file in path.rglob("*")
                    if file.is_file()
                ),
                key=lambda pair: pair[0],
            )
            results = [
                self._ingest_one(file, parser, dry_run)
                for file, parser in pairs
                if parser is not None
            ]

        skipped = sum(1 for r in results if r.skipped)
        failed = sum(1 for r in results if r.error is not None)
        logger.info(
            "ingestion run finished: path=%s processed=%d skipped=%d failed=%d",
            path,
            len(results),
            skipped,
            failed,
        )
        return results

    def _ingest_one(self, path: Path, parser: Parser, dry_run: bool) -> IngestionResult:
        try:
            content_hash = hashlib.sha256(path.read_bytes()).hexdigest()
            if self._writer.get_source_content_hash(str(path)) == content_hash:
                return IngestionResult(path=path, skipped=True)

            document = parser.parse(path)
            if not dry_run:
                document = self._enricher.enrich(document)
                self._writer.write(document)
            return IngestionResult(
                path=path,
                skipped=False,
                sections=len(document.sections),
                chunks=len(document.chunks),
                code_entities=len(document.code_entities),
                policy_rules=len(document.policy_rules),
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("failed to ingest %s", path)
            return IngestionResult(path=path, skipped=False, error=str(exc))
