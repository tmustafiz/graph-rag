from contextlib import asynccontextmanager
from pathlib import Path

from fastapi.testclient import TestClient
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route

from graph_rag.http_app import build_http_app
from graph_rag.ingestion_result import IngestionResult


class _FakePipeline:
    def run(self, path: Path, dry_run: bool = False) -> list[IngestionResult]:
        return [IngestionResult(path=path, skipped=False, sections=1)]


def _fake_mcp_app(lifespan_events: list[str]) -> Starlette:
    async def ping(request):  # noqa: ANN001, ARG001
        return PlainTextResponse("pong")

    @asynccontextmanager
    async def lifespan(app: Starlette):  # noqa: ARG001
        lifespan_events.append("started")
        yield
        lifespan_events.append("stopped")

    return Starlette(routes=[Route("/mcp-ping", ping)], lifespan=lifespan)


def test_mounted_mcp_app_lifespan_starts_and_stops() -> None:
    lifespan_events: list[str] = []
    app = build_http_app(_fake_mcp_app(lifespan_events), _FakePipeline())

    with TestClient(app):
        assert lifespan_events == ["started"]

    assert lifespan_events == ["started", "stopped"]


def test_ingest_route_is_reachable_on_the_combined_app() -> None:
    app = build_http_app(_fake_mcp_app([]), _FakePipeline())

    with TestClient(app) as client:
        response = client.post("/ingest", json={"path": "notes.md"})

    assert response.status_code == 200
    assert response.json()[0]["path"] == "notes.md"


def test_mounted_mcp_app_route_is_reachable_through_the_mount() -> None:
    app = build_http_app(_fake_mcp_app([]), _FakePipeline())

    with TestClient(app) as client:
        response = client.get("/mcp-ping")

    assert response.status_code == 200
    assert response.text == "pong"
