from pathlib import Path

from fastapi import APIRouter, HTTPException

from .ingest_request import IngestRequest
from .ingestion_pipeline import IngestionPipeline
from .ingestion_result import IngestionResult
from .unsupported_file_type_error import UnsupportedFileTypeError


def build_ingest_router(pipeline: IngestionPipeline) -> APIRouter:
    """`POST /ingest` — the same operation as the `ingest_path` MCP tool, over
    plain HTTP, for triggering ingestion from CI or a pre-commit hook without
    an MCP client. FastAPI validates the request body (`IngestRequest`)
    automatically, returning 422 for a missing/malformed one.
    """
    router = APIRouter()

    @router.post("/ingest", response_model=list[IngestionResult])
    def ingest_endpoint(request: IngestRequest) -> list[IngestionResult]:
        try:
            return pipeline.run(Path(request.path), dry_run=request.dry_run)
        except UnsupportedFileTypeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return router
