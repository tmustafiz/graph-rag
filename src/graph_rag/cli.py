from pathlib import Path

import typer
import uvicorn
from mcp.server.transport_security import TransportSecuritySettings

from .graph.client import check_connectivity, driver_session
from .graph.graph_writer import GraphWriter
from .graph.schema import apply_schema
from .ingest.embedders import SentenceTransformerEmbedder
from .ingest.parser_registry import ParserRegistry
from .ingestion_pipeline import IngestionPipeline
from .mcp_server.bearer_token_middleware import BearerTokenMiddleware
from .mcp_server.retriever import Retriever
from .mcp_server.server import build_server
from .settings import settings
from .unsupported_file_type_error import UnsupportedFileTypeError

app = typer.Typer(
    name="graph-rag",
    help="Graph RAG knowledge base for coding agents (Neo4j-backed, exposed over MCP).",
    no_args_is_help=True,
)


@app.command()
def status() -> None:
    """Check connectivity to the Neo4j graph database."""
    try:
        check_connectivity()
    except Exception as exc:  # noqa: BLE001
        typer.secho(f"Neo4j unreachable: {exc}", fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc
    typer.secho("Neo4j is reachable.", fg=typer.colors.GREEN)


@app.command(name="apply-schema")
def apply_schema_command() -> None:
    """Create (or verify) Neo4j constraints and indexes. Idempotent."""
    try:
        with driver_session() as driver:
            statements = apply_schema(driver)
    except Exception as exc:  # noqa: BLE001
        typer.secho(f"Failed to apply schema: {exc}", fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc
    typer.secho(f"Applied {len(statements)} constraints/indexes.", fg=typer.colors.GREEN)


@app.command()
def ingest(
    path: Path = typer.Argument(..., exists=True, help="File or directory to ingest."),  # noqa: B008
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Preview what would be ingested without writing to Neo4j."
    ),
) -> None:
    """Parse, chunk, embed, and upsert a file or directory (recursive) into the graph.

    Skips any file whose content is unchanged since the last ingest.
    """
    with driver_session() as driver:
        pipeline = IngestionPipeline(
            ParserRegistry(), SentenceTransformerEmbedder(), GraphWriter(driver)
        )
        try:
            results = pipeline.run(path, dry_run=dry_run)
        except UnsupportedFileTypeError as exc:
            typer.secho(str(exc), fg=typer.colors.RED)
            raise typer.Exit(code=1) from exc

    verb = "Would ingest" if dry_run else "Ingested"
    for result in results:
        if result.skipped:
            typer.echo(f"Skipped {result.path} (unchanged).")
            continue
        typer.secho(
            f"{verb} {result.path}: {result.sections} sections, {result.chunks} chunks, "
            f"{result.code_entities} code entities, {result.policy_rules} policy rules.",
            fg=typer.colors.GREEN,
        )


@app.command(name="serve-mcp")
def serve_mcp() -> None:
    """Run the MCP server (Streamable HTTP) for coding-agent lookups."""
    # Explicit (not left to the SDK's host-based default) so Origin/DNS-rebinding
    # protection stays on even when MCP_HOST=0.0.0.0 (e.g. binding inside a container
    # for Docker's port-forwarding to reach it, while the host-side publish still
    # restricts external access to 127.0.0.1).
    transport_security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=["127.0.0.1:*", "localhost:*", f"{settings.mcp_host}:*"],
        allowed_origins=["http://127.0.0.1:*", "http://localhost:*", f"http://{settings.mcp_host}:*"],
    )

    embedder = SentenceTransformerEmbedder()
    with driver_session() as driver:
        retriever = Retriever(driver, embedder)
        writer = GraphWriter(driver)
        ingestion_pipeline = IngestionPipeline(ParserRegistry(), embedder, writer)
        mcp_app = build_server(retriever, ingestion_pipeline).streamable_http_app(
            host=settings.mcp_host, transport_security=transport_security
        )
        if settings.mcp_auth_token:
            mcp_app = BearerTokenMiddleware(mcp_app, token=settings.mcp_auth_token)

        typer.echo(f"MCP server listening on http://{settings.mcp_host}:{settings.mcp_port}/mcp")
        uvicorn.run(mcp_app, host=settings.mcp_host, port=settings.mcp_port, log_level="info")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
