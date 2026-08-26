import time
from pathlib import Path

from watchdog.observers import Observer

from .ingestion_pipeline import IngestionPipeline
from .ingestion_watch_handler import IngestionWatchHandler


class IngestionWatcher:
    """Blocks, re-ingesting `path` via `IngestionPipeline` on every filesystem
    change, until interrupted (Ctrl+C) — the long-running half of
    `graph-rag ingest --watch`, for continuous local dev.
    """

    def __init__(self, pipeline: IngestionPipeline, dry_run: bool = False) -> None:
        self._pipeline = pipeline
        self._dry_run = dry_run

    def watch(self, path: Path) -> None:
        observer = Observer()
        if path.is_file():
            # Watchdog watches directories; a single-file target is watched via
            # its parent, with the handler filtered to just that file so sibling
            # file changes in the same directory don't trigger a re-ingest.
            handler = IngestionWatchHandler(self._pipeline, self._dry_run, only_path=path)
            observer.schedule(handler, str(path.parent), recursive=False)
        else:
            handler = IngestionWatchHandler(self._pipeline, self._dry_run)
            observer.schedule(handler, str(path), recursive=True)

        observer.start()
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        finally:
            observer.stop()
            observer.join()
