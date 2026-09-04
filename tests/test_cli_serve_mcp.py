from contextlib import contextmanager
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from graph_rag.cli import app

runner = CliRunner()


@contextmanager
def _fake_driver_session():
    yield MagicMock(name="driver")


def _run_serve_mcp(args: list[str]) -> tuple[MagicMock, MagicMock]:
    server = MagicMock(name="server")
    with (
        patch("graph_rag.cli.build_embedder", MagicMock()),
        patch("graph_rag.cli.driver_session", _fake_driver_session),
        patch("graph_rag.cli.Retriever", MagicMock()),
        patch("graph_rag.cli.GraphWriter", MagicMock()),
        patch("graph_rag.cli.IngestionPipeline", MagicMock()),
        patch("graph_rag.cli.MemoryWriter", MagicMock()),
        patch("graph_rag.cli.MemoryRecaller", MagicMock()),
        patch("graph_rag.cli.build_server", MagicMock(return_value=server)),
        patch("graph_rag.cli.build_http_app", MagicMock()),
        patch("graph_rag.cli.BearerTokenMiddleware", MagicMock()),
        patch("graph_rag.cli.uvicorn.run", MagicMock()) as uvicorn_run,
    ):
        result = runner.invoke(app, ["serve-mcp", *args])
    assert result.exit_code == 0, result.output
    return server, uvicorn_run


def test_stdio_flag_runs_stdio_transport_and_never_starts_uvicorn() -> None:
    server, uvicorn_run = _run_serve_mcp(["--stdio"])

    server.run.assert_called_once_with(transport="stdio")
    server.streamable_http_app.assert_not_called()
    uvicorn_run.assert_not_called()


def test_default_serves_streamable_http_and_not_stdio() -> None:
    server, uvicorn_run = _run_serve_mcp([])

    server.streamable_http_app.assert_called_once()
    server.run.assert_not_called()
    uvicorn_run.assert_called_once()


def test_role_knowledge_builds_only_the_knowledge_server_and_mounts_ingest() -> None:
    server = MagicMock(name="server")
    with (
        patch("graph_rag.cli.build_embedder", MagicMock()),
        patch("graph_rag.cli.driver_session", _fake_driver_session),
        patch("graph_rag.cli.Retriever", MagicMock()),
        patch("graph_rag.cli.GraphWriter", MagicMock()),
        patch("graph_rag.cli.IngestionPipeline", MagicMock()),
        patch("graph_rag.cli.MemoryWriter", MagicMock()) as memory_writer_cls,
        patch("graph_rag.cli.MemoryRecaller", MagicMock()) as memory_recaller_cls,
        patch(
            "graph_rag.cli.build_knowledge_server", MagicMock(return_value=server)
        ) as build_knowledge,
        patch("graph_rag.cli.build_memory_server", MagicMock()) as build_memory,
        patch("graph_rag.cli.build_server", MagicMock()) as build_all,
        patch("graph_rag.cli.build_http_app", MagicMock(return_value=MagicMock())) as build_http,
        patch("graph_rag.cli.BearerTokenMiddleware", MagicMock()),
        patch("graph_rag.cli.uvicorn.run", MagicMock()),
    ):
        result = runner.invoke(app, ["serve-mcp", "--role", "knowledge"])

    assert result.exit_code == 0, result.output
    build_knowledge.assert_called_once()
    build_memory.assert_not_called()
    build_all.assert_not_called()
    memory_writer_cls.assert_not_called()
    memory_recaller_cls.assert_not_called()
    build_http.assert_called_once()
    assert "/ingest" in result.stdout


def test_role_memory_builds_only_the_memory_server_and_skips_the_ingest_mount() -> None:
    server = MagicMock(name="server")
    with (
        patch("graph_rag.cli.build_embedder", MagicMock()),
        patch("graph_rag.cli.driver_session", _fake_driver_session),
        patch("graph_rag.cli.Retriever", MagicMock()) as retriever_cls,
        patch("graph_rag.cli.GraphWriter", MagicMock()) as graph_writer_cls,
        patch("graph_rag.cli.IngestionPipeline", MagicMock()) as ingestion_pipeline_cls,
        patch("graph_rag.cli.MemoryWriter", MagicMock()),
        patch("graph_rag.cli.MemoryRecaller", MagicMock()),
        patch("graph_rag.cli.build_knowledge_server", MagicMock()) as build_knowledge,
        patch("graph_rag.cli.build_memory_server", MagicMock(return_value=server)) as build_memory,
        patch("graph_rag.cli.build_server", MagicMock()) as build_all,
        patch("graph_rag.cli.build_http_app", MagicMock()) as build_http,
        patch("graph_rag.cli.BearerTokenMiddleware", MagicMock()),
        patch("graph_rag.cli.uvicorn.run", MagicMock()),
    ):
        result = runner.invoke(app, ["serve-mcp", "--role", "memory"])

    assert result.exit_code == 0, result.output
    build_memory.assert_called_once()
    build_knowledge.assert_not_called()
    build_all.assert_not_called()
    retriever_cls.assert_not_called()
    graph_writer_cls.assert_not_called()
    ingestion_pipeline_cls.assert_not_called()
    build_http.assert_not_called()
    assert "/ingest" not in result.stdout


def test_invalid_role_is_rejected() -> None:
    result = runner.invoke(app, ["serve-mcp", "--role", "bogus"])
    assert result.exit_code != 0


def test_stdio_status_line_goes_to_stderr_not_stdout() -> None:
    server = MagicMock(name="server")
    captured = {}

    def _capture_run(*_args, **_kwargs):
        # `typer.echo(..., err=True)` has already fired by the time run() is called.
        captured["ran"] = True

    server.run.side_effect = _capture_run
    with (
        patch("graph_rag.cli.build_embedder", MagicMock()),
        patch("graph_rag.cli.driver_session", _fake_driver_session),
        patch("graph_rag.cli.Retriever", MagicMock()),
        patch("graph_rag.cli.GraphWriter", MagicMock()),
        patch("graph_rag.cli.IngestionPipeline", MagicMock()),
        patch("graph_rag.cli.MemoryWriter", MagicMock()),
        patch("graph_rag.cli.MemoryRecaller", MagicMock()),
        patch("graph_rag.cli.build_server", MagicMock(return_value=server)),
        patch("graph_rag.cli.uvicorn.run", MagicMock()),
    ):
        result = runner.invoke(app, ["serve-mcp", "--stdio"])

    assert result.exit_code == 0, result.output
    assert captured.get("ran") is True
    assert result.stdout == ""
    assert "stdio" in result.stderr
