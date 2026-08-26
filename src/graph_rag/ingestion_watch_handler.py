import logging
from pathlib import Path

from watchdog.events import FileSystemEvent, FileSystemEventHandler

from .ingestion_pipeline import IngestionPipeline
from .unsupported_file_type_error import UnsupportedFileTypeError

logger = logging.getLogger(__name__)


class IngestionWatchHandler(FileSystemEventHandler):
    """Re-ingests a single file via `IngestionPipeline` on every create/modify
    filesystem event — the reaction half of `graph-rag ingest --watch`.

    Relies on `IngestionPipeline`'s own content-hash skip and per-file error
    handling, so a duplicate or unrelated event is cheap, not just ignored.
    """

    def __init__(
        self, pipeline: IngestionPipeline, dry_run: bool = False, only_path: Path | None = None
    ) -> None:
        self._pipeline = pipeline
        self._dry_run = dry_run
        self._only_path = only_path.resolve() if only_path is not None else None

    def on_created(self, event: FileSystemEvent) -> None:
        self._handle(event)

    def on_modified(self, event: FileSystemEvent) -> None:
        self._handle(event)

    def _handle(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        path = Path(str(event.src_path))
        if self._only_path is not None and path.resolve() != self._only_path:
            return
        try:
            for result in self._pipeline.run(path, dry_run=self._dry_run):
                if result.error is not None:
                    logger.error("failed to ingest %s: %s", result.path, result.error)
                elif not result.skipped:
                    logger.info("re-ingested %s", result.path)
        except UnsupportedFileTypeError:
            pass  # not every filesystem event under a watched directory is a parseable file
