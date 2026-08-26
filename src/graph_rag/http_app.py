from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.applications import Starlette

from .ingest_http_endpoint import build_ingest_router
from .ingestion_pipeline import IngestionPipeline


def build_http_app(mcp_app: Starlette, ingestion_pipeline: IngestionPipeline) -> FastAPI:
    """Combines the MCP server's own Starlette app with a FastAPI-routed
    `POST /ingest` endpoint into one ASGI app, served together by `serve-mcp`.

    FastAPI is the top-level app; `mcp_app` is mounted underneath it.
    Starlette's `Mount()` does not forward `lifespan` startup/shutdown events
    to a mounted child app by default, which would silently break the MCP
    session manager's own startup (it starts inside `mcp_app`'s lifespan) —
    so `mcp_app`'s lifespan is entered explicitly inside this app's lifespan
    instead of relying on the mount alone.
    """

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        async with mcp_app.router.lifespan_context(mcp_app):
            yield

    app = FastAPI(lifespan=lifespan)
    app.include_router(build_ingest_router(ingestion_pipeline))
    app.mount("/", mcp_app)
    return app
