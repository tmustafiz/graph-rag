from pathlib import Path

import pytest

from graph_rag.ingest.embedders import Embedder
from graph_rag.ingest.models import ParsedDocument
from graph_rag.ingest.parser_registry import ParserRegistry
from graph_rag.ingestion_pipeline import IngestionPipeline
from graph_rag.unsupported_file_type_error import UnsupportedFileTypeError


class _FakeEmbedder(Embedder):
    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] for _ in texts]


class _FakeGraphWriter:
    def __init__(self) -> None:
        self.written: list[ParsedDocument] = []
        self._content_hashes: dict[str, str] = {}

    def get_source_content_hash(self, path: str) -> str | None:
        return self._content_hashes.get(path)

    def write(self, document: ParsedDocument) -> None:
        self.written.append(document)
        self._content_hashes[document.source.path] = document.source.content_hash


def _pipeline(writer: _FakeGraphWriter) -> IngestionPipeline:
    return IngestionPipeline(ParserRegistry(), _FakeEmbedder(), writer)


def test_run_on_single_file_parses_and_writes(tmp_path: Path) -> None:
    path = tmp_path / "notes.md"
    path.write_text("# Title\n\nSome text.\n")
    writer = _FakeGraphWriter()

    results = _pipeline(writer).run(path)

    assert len(results) == 1
    assert results[0].skipped is False
    assert results[0].sections == 1
    assert len(writer.written) == 1


def test_run_skips_file_with_unchanged_content_hash(tmp_path: Path) -> None:
    path = tmp_path / "notes.md"
    path.write_text("# Title\n\nSome text.\n")
    writer = _FakeGraphWriter()
    pipeline = _pipeline(writer)

    pipeline.run(path)
    results = pipeline.run(path)

    assert results[0].skipped is True
    assert len(writer.written) == 1


def test_run_reingests_file_after_content_changes(tmp_path: Path) -> None:
    path = tmp_path / "notes.md"
    path.write_text("# Title\n\nSome text.\n")
    writer = _FakeGraphWriter()
    pipeline = _pipeline(writer)

    pipeline.run(path)
    path.write_text("# Title\n\nChanged text.\n")
    results = pipeline.run(path)

    assert results[0].skipped is False
    assert len(writer.written) == 2


def test_dry_run_does_not_write(tmp_path: Path) -> None:
    path = tmp_path / "notes.md"
    path.write_text("# Title\n\nSome text.\n")
    writer = _FakeGraphWriter()

    results = _pipeline(writer).run(path, dry_run=True)

    assert results[0].skipped is False
    assert results[0].sections == 1
    assert writer.written == []


def test_run_on_unsupported_single_file_raises(tmp_path: Path) -> None:
    path = tmp_path / "image.png"
    path.write_bytes(b"not-really-a-png")
    writer = _FakeGraphWriter()

    with pytest.raises(UnsupportedFileTypeError):
        _pipeline(writer).run(path)


def test_run_on_directory_recurses_and_skips_unsupported_files(tmp_path: Path) -> None:
    (tmp_path / "notes.md").write_text("# Title\n\nSome text.\n")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "mod.py").write_text("def helper() -> None:\n    pass\n")
    (sub / "image.png").write_bytes(b"not-really-a-png")
    writer = _FakeGraphWriter()

    results = _pipeline(writer).run(tmp_path)

    ingested_paths = {result.path.name for result in results}
    assert ingested_paths == {"notes.md", "mod.py"}
    assert len(writer.written) == 2
