import hashlib
import logging
from pathlib import Path
from typing import Protocol

from .graph.graph_writer import GraphWriter
from .ingest.embedders import Embedder
from .ingest.enricher import Enricher
from .ingest.parser import Parser
from .ingest.parser_registry import ParserRegistry
from .ingestion_result import IngestionResult
from .settings import settings
from .unsupported_file_type_error import UnsupportedFileTypeError

logger = logging.getLogger(__name__)

_BUILD_FILE_NAMES = ("pom.xml", "build.gradle", "build.gradle.kts", "settings.gradle")


class PostIngestResolver(Protocol):
    """A graph pass run once after an ingest completes (project model, Spring
    beans, …) — after both a directory ingest and a single-file ingest, since
    each resolver is a full-graph rebuild. Idempotent; returns a small stats
    dict for logging.
    """

    def resolve(self) -> dict[str, int]: ...


def _ingest_rank(path: Path) -> int:
    """Directory ingest order: build files first (so `Module` nodes exist
    before the `.java` files that resolve against them), then everything else.
    """
    if path.name in _BUILD_FILE_NAMES or path.name.endswith((".gradle", ".gradle.kts")):
        return 0
    return 1


_GENERATED_SOURCE_PARTS = {"generated-sources", "generated-test-sources", "generated"}


def _is_generated_source(path: Path) -> bool:
    """A `.java` file living under an annotation-processor output directory
    (`target/generated-sources`, `build/generated`, …) — only meaningful after
    a build, so `GRAG_INGEST_GENERATED_SOURCES=false` skips it.
    """
    if path.suffix.lower() != ".java":
        return False
    parts = set(path.parts)
    return bool(parts & _GENERATED_SOURCE_PARTS) and bool(parts & {"target", "build"})


class IngestionPipeline:
    """Parses, embeds, and upserts a file or directory (recursive) into the graph.

    Skips any file whose content hash matches what's already stored for its
    `Source` (no re-parse, no re-embedding). `dry_run=True` parses to report
    what would change without generating embeddings or writing to Neo4j. A
    file that fails to parse/embed/write is recorded as an `IngestionResult`
    with `error` set, rather than aborting the rest of the batch.
    """

    def __init__(
        self,
        registry: ParserRegistry,
        embedder: Embedder,
        writer: GraphWriter,
        resolvers: list[PostIngestResolver] | None = None,
    ) -> None:
        self._registry = registry
        self._enricher = Enricher(embedder)
        self._writer = writer
        self._resolvers = resolvers or []

    def run(self, path: Path, dry_run: bool = False) -> list[IngestionResult]:
        logger.info("ingestion run starting: path=%s dry_run=%s", path, dry_run)
        skip_generated = not settings.ingest_generated_sources

        if path.is_file():
            if skip_generated and _is_generated_source(path):
                return [IngestionResult(path=path, skipped=True)]
            parser = self._registry.for_path(path)
            if parser is None:
                raise UnsupportedFileTypeError(path)
            results = [self._ingest_one(path, parser, dry_run)]
            # a single-file ingest still re-projects the whole graph: the
            # resolvers are full rebuilds, so `ingest_path` / `grag ingest
            # <file>` / `--watch` keep `:Bean` / `IN_MODULE` / `MANAGES` / …
            # in sync with the edit (#120)
            if not dry_run:
                for resolver in self._resolvers:
                    resolver.resolve()
        else:
            pairs = sorted(
                (
                    (file, self._registry.for_path(file))
                    for file in path.rglob("*")
                    if file.is_file() and not (skip_generated and _is_generated_source(file))
                ),
                key=lambda pair: (_ingest_rank(pair[0]), pair[0]),
            )
            results = [
                self._ingest_one(file, parser, dry_run)
                for file, parser in pairs
                if parser is not None
            ]
            if not dry_run:
                for resolver in self._resolvers:
                    resolver.resolve()

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
                db_objects=(
                    len(document.db_tables)
                    + len(document.db_columns)
                    + len(document.db_views)
                    + len(document.db_indexes)
                ),
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("failed to ingest %s", path)
            return IngestionResult(path=path, skipped=False, error=str(exc))
