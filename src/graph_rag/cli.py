from pathlib import Path

import typer
import uvicorn
from mcp.server.transport_security import TransportSecuritySettings

from .graph.client import check_connectivity, driver_session
from .graph.graph_writer import GraphWriter
from .graph.schema import apply_schema
from .ingest.embedders import SentenceTransformerEmbedder
from .ingest.enricher import Enricher
from .ingest.parsers import MarkdownParser, PdfParser, PythonParser, YamlParser
from .mcp_server.bearer_token_middleware import BearerTokenMiddleware
from .mcp_server.retriever import Retriever
from .mcp_server.server import build_server
from .settings import settings

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
    path: Path = typer.Argument(..., exists=True, dir_okay=False, help="File to ingest."),  # noqa: B008
) -> None:
    """Parse, chunk, embed, and upsert a document into the graph."""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        parser = PdfParser()
    elif suffix in (".md", ".markdown"):
        parser = MarkdownParser()
    elif suffix == ".py":
        parser = PythonParser()
    elif suffix in (".yaml", ".yml"):
        parser = YamlParser()
    else:
        typer.secho(
            f"Unsupported file type: {path.suffix} (only .pdf/.md/.py/.yaml/.yml for now)",
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=1)

    typer.echo(f"Parsing {path}...")
    document = parser.parse(path)
    typer.echo(
        f"Parsed {len(document.sections)} sections, {len(document.chunks)} chunks, "
        f"{len(document.code_entities)} code entities, {len(document.policy_rules)} policy rules."
    )

    typer.echo("Generating embeddings...")
    document = Enricher(SentenceTransformerEmbedder()).enrich(document)

    typer.echo("Writing to Neo4j...")
    with driver_session() as driver:
        GraphWriter(driver).write(document)

    typer.secho(
        f"Ingested {path}: {len(document.sections)} sections, {len(document.chunks)} chunks, "
        f"{len(document.code_entities)} code entities, {len(document.policy_rules)} policy rules.",
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
        mcp_app = build_server(retriever).streamable_http_app(
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
