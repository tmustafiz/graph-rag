import logging
from pathlib import Path

import typer
import uvicorn
from mcp.server.transport_security import TransportSecuritySettings

from .eval.retrieval_evaluator import RetrievalEvaluator
from .graph.client import check_connectivity, driver_session
from .graph.graph_writer import GraphWriter
from .graph.schema import apply_schema
from .http_app import build_http_app
from .ingest.embedders import SentenceTransformerEmbedder
from .ingest.parser_registry import ParserRegistry
from .ingestion_pipeline import IngestionPipeline
from .ingestion_watcher import IngestionWatcher
from .mcp_server.bearer_token_middleware import BearerTokenMiddleware
from .mcp_server.retriever import Retriever
from .mcp_server.server import build_server
from .memory import MemoryPruner, MemoryRecaller, MemoryWriter
from .settings import settings
from .unsupported_file_type_error import UnsupportedFileTypeError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

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
    watch: bool = typer.Option(
        False,
        "--watch",
        help="After the initial ingest, watch `path` for changes and re-ingest "
        "continuously (Ctrl+C to stop).",
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
        any_failed = False
        for result in results:
            if result.error is not None:
                any_failed = True
                typer.secho(f"Failed to ingest {result.path}: {result.error}", fg=typer.colors.RED)
                continue
            if result.skipped:
                typer.echo(f"Skipped {result.path} (unchanged).")
                continue
            typer.secho(
                f"{verb} {result.path}: {result.sections} sections, {result.chunks} chunks, "
                f"{result.code_entities} code entities, {result.policy_rules} policy rules.",
                fg=typer.colors.GREEN,
            )

        if watch:
            typer.echo(f"Watching {path} for changes... (Ctrl+C to stop)")
            IngestionWatcher(pipeline, dry_run=dry_run).watch(path)
            return

    if any_failed:
        raise typer.Exit(code=1)


@app.command(name="prune-memory")
def prune_memory(
    threshold: float = typer.Option(
        ...,
        "--threshold",
        help="Decay score threshold; memories scoring below this are soft-deleted.",
    ),
    grace_days: int = typer.Option(
        30, "--grace-days", help="Days a soft-deleted memory is kept before hard-delete."
    ),
) -> None:
    """Soft-delete low recency+frequency-score memories; hard-delete ones past the grace window."""
    with driver_session() as driver:
        result = MemoryPruner(driver).prune(threshold, grace_days=grace_days)
    typer.secho(
        f"Soft-deleted {result.soft_deleted} memories, hard-deleted {result.hard_deleted}.",
        fg=typer.colors.GREEN,
    )


@app.command(name="eval-retrieval")
def eval_retrieval(
    eval_set: Path | None = typer.Option(  # noqa: B008
        None, "--eval-set", help="Path to a YAML eval-case file (default: the built-in set)."
    ),
) -> None:
    """Run the hand-written retrieval eval set against `search()`; reports pass/fail per case."""
    cases = RetrievalEvaluator.load_cases(eval_set)
    embedder = SentenceTransformerEmbedder()
    with driver_session() as driver:
        results = RetrievalEvaluator(Retriever(driver, embedder)).run(cases)

    for result in results:
        status = "PASS" if result.passed else "FAIL"
        color = typer.colors.GREEN if result.passed else typer.colors.RED
        rank_note = f" (rank {result.best_rank})" if result.passed else ""
        typer.secho(f"[{status}] {result.case.query}{rank_note}", fg=color)

    passed = sum(1 for r in results if r.passed)
    typer.echo(f"{passed}/{len(results)} passed.")
    if passed < len(results):
        raise typer.Exit(code=1)


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
        allowed_origins=[
            "http://127.0.0.1:*",
            "http://localhost:*",
            f"http://{settings.mcp_host}:*",
        ],
    )

    embedder = SentenceTransformerEmbedder()
    with driver_session() as driver:
        retriever = Retriever(driver, embedder)
        writer = GraphWriter(driver)
        ingestion_pipeline = IngestionPipeline(ParserRegistry(), embedder, writer)
        memory_writer = MemoryWriter(driver, embedder)
        memory_recaller = MemoryRecaller(driver, embedder)
        mcp_app = build_server(
            retriever, ingestion_pipeline, memory_writer, memory_recaller
        ).streamable_http_app(host=settings.mcp_host, transport_security=transport_security)
        app = build_http_app(mcp_app, ingestion_pipeline)
        if settings.mcp_auth_token:
            app = BearerTokenMiddleware(app, token=settings.mcp_auth_token)

        typer.echo(f"MCP server listening on http://{settings.mcp_host}:{settings.mcp_port}/mcp")
        typer.echo(
            f"POST /ingest listening on http://{settings.mcp_host}:{settings.mcp_port}/ingest"
        )
        uvicorn.run(app, host=settings.mcp_host, port=settings.mcp_port, log_level="info")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
