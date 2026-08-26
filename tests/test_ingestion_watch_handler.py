from pathlib import Path

import pytest
from watchdog.events import DirModifiedEvent, FileCreatedEvent, FileModifiedEvent

from graph_rag.ingestion_result import IngestionResult
from graph_rag.ingestion_watch_handler import IngestionWatchHandler
from graph_rag.unsupported_file_type_error import UnsupportedFileTypeError


class _FakePipeline:
    def __init__(self, results: list[IngestionResult] | None = None) -> None:
        self.calls: list[Path] = []
        self._results = results if results is not None else []
        self.raise_unsupported = False

    def run(self, path: Path, dry_run: bool = False) -> list[IngestionResult]:
        self.calls.append(path)
        if self.raise_unsupported:
            raise UnsupportedFileTypeError(path)
        return self._results


def test_handle_ignores_directory_events() -> None:
    pipeline = _FakePipeline()
    handler = IngestionWatchHandler(pipeline)

    handler.on_modified(DirModifiedEvent("/tmp/some-dir"))

    assert pipeline.calls == []


def test_handle_reingests_on_matching_file_event() -> None:
    pipeline = _FakePipeline()
    handler = IngestionWatchHandler(pipeline)

    handler.on_created(FileCreatedEvent("/tmp/notes.md"))

    assert pipeline.calls == [Path("/tmp/notes.md")]


def test_handle_ignores_events_outside_only_path(tmp_path: Path) -> None:
    target = tmp_path / "target.py"
    target.write_text("x = 1\n")
    sibling = tmp_path / "sibling.py"
    sibling.write_text("y = 2\n")
    pipeline = _FakePipeline()
    handler = IngestionWatchHandler(pipeline, only_path=target)

    handler.on_modified(FileModifiedEvent(str(sibling)))
    assert pipeline.calls == []

    handler.on_modified(FileModifiedEvent(str(target)))
    assert pipeline.calls == [target]


def test_handle_swallows_unsupported_file_type_error() -> None:
    pipeline = _FakePipeline()
    pipeline.raise_unsupported = True
    handler = IngestionWatchHandler(pipeline)

    handler.on_created(FileCreatedEvent("/tmp/image.png"))  # must not raise

    assert pipeline.calls == [Path("/tmp/image.png")]


def test_handle_logs_but_does_not_raise_on_ingestion_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    pipeline = _FakePipeline(
        results=[IngestionResult(path=Path("/tmp/broken.yaml"), skipped=False, error="boom")]
    )
    handler = IngestionWatchHandler(pipeline)

    with caplog.at_level("ERROR"):
        handler.on_modified(FileModifiedEvent("/tmp/broken.yaml"))

    assert "boom" in caplog.text
