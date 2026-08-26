from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from graph_rag.ingest_http_endpoint import build_ingest_router
from graph_rag.ingestion_result import IngestionResult
from graph_rag.unsupported_file_type_error import UnsupportedFileTypeError


class _FakePipeline:
    def __init__(self, results: list[IngestionResult] | None = None) -> None:
        self.calls: list[tuple[Path, bool]] = []
        self._results = results if results is not None else []
        self.raise_unsupported_for: Path | None = None

    def run(self, path: Path, dry_run: bool = False) -> list[IngestionResult]:
        self.calls.append((path, dry_run))
        if self.raise_unsupported_for == path:
            raise UnsupportedFileTypeError(path)
        return self._results


def _client(pipeline: _FakePipeline) -> TestClient:
    app = FastAPI()
    app.include_router(build_ingest_router(pipeline))
    return TestClient(app)


def test_post_ingest_runs_pipeline_and_returns_results() -> None:
    pipeline = _FakePipeline(
        results=[IngestionResult(path=Path("notes.md"), skipped=False, sections=1, chunks=2)]
    )
    response = _client(pipeline).post("/ingest", json={"path": "notes.md"})

    assert response.status_code == 200
    body = response.json()
    assert body[0]["path"] == "notes.md"
    assert body[0]["chunks"] == 2
    assert pipeline.calls == [(Path("notes.md"), False)]


def test_post_ingest_passes_through_dry_run() -> None:
    pipeline = _FakePipeline()
    _client(pipeline).post("/ingest", json={"path": "notes.md", "dry_run": True})

    assert pipeline.calls == [(Path("notes.md"), True)]


def test_post_ingest_missing_path_returns_422() -> None:
    response = _client(_FakePipeline()).post("/ingest", json={})

    assert response.status_code == 422


def test_post_ingest_invalid_json_returns_422() -> None:
    response = _client(_FakePipeline()).post(
        "/ingest", content=b"not json", headers={"content-type": "application/json"}
    )

    assert response.status_code == 422


def test_post_ingest_unsupported_file_type_returns_400() -> None:
    pipeline = _FakePipeline()
    pipeline.raise_unsupported_for = Path("image.png")

    response = _client(pipeline).post("/ingest", json={"path": "image.png"})

    assert response.status_code == 400
    assert "Unsupported file type" in response.json()["detail"]
