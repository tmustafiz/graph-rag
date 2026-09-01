import logging
from pathlib import Path

import typer
import uvicorn
from mcp.server.transport_security import TransportSecuritySettings

from .eval.retrieval_evaluator import EVAL_CORPUS_DIR, RetrievalEvaluator
from .graph.centrality_analyzer import CentralityAnalyzer
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
    name="grag-mcp",
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


@app.command(name="compute-centrality")
def compute_centrality() -> None:
    """Run PageRank over the CodeEntity CALLS/IMPORTS graph, writing scores
    to CodeEntity.pagerank. Re-run after ingesting code changes.
    """
    with driver_session() as driver:
        scored = CentralityAnalyzer(driver).compute_code_pagerank()
    if scored == 0:
        typer.secho(
            "No CodeEntity CALLS/IMPORTS edges found — ingest some Python source first.",
            fg=typer.colors.YELLOW,
        )
        return
    typer.secho(f"Scored {scored} code entities.", fg=typer.colors.GREEN)


@app.command(name="eval-retrieval")
def eval_retrieval(
    eval_set: Path | None = typer.Option(  # noqa: B008
        None, "--eval-set", help="Path to a YAML eval-case file (default: the built-in set)."
    ),
) -> None:
    """Run the hand-written retrieval eval set against `search()`; reports pass/fail per case.

    Ingests the fixture corpus in `src/graph_rag/eval/corpus/` first (idempotent),
    so the eval is self-contained. Run from the repo root.
    """
    cases = RetrievalEvaluator.load_cases(eval_set)
    embedder = SentenceTransformerEmbedder()
    with driver_session() as driver:
        if not EVAL_CORPUS_DIR.is_dir():
            typer.secho(
                f"Eval corpus not found at {EVAL_CORPUS_DIR} — run this from the repo root.",
                fg=typer.colors.RED,
            )
            raise typer.Exit(code=1)
        pipeline = IngestionPipeline(ParserRegistry(), embedder, GraphWriter(driver))
        pipeline.run(EVAL_CORPUS_DIR)
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
def serve_mcp(
    stdio: bool = typer.Option(
        False,
        "--stdio",
        help="Serve over stdio instead of Streamable HTTP, for MCP clients that "
        "launch the server as a subprocess (Claude Desktop, etc.). No network "
        "socket, no auth-token gate, and no POST /ingest endpoint.",
    ),
) -> None:
    """Run the MCP server for coding-agent lookups.

    Defaults to Streamable HTTP (a long-lived, container-friendly listener on
    MCP_HOST:MCP_PORT). Pass --stdio for a zero-config drop-in that the client
    spawns per session and talks to over stdin/stdout.
    """
    embedder = SentenceTransformerEmbedder()
    with driver_session() as driver:
        retriever = Retriever(driver, embedder)
        writer = GraphWriter(driver)
        ingestion_pipeline = IngestionPipeline(ParserRegistry(), embedder, writer)
        memory_writer = MemoryWriter(driver, embedder)
        memory_recaller = MemoryRecaller(driver, embedder)
        server = build_server(retriever, ingestion_pipeline, memory_writer, memory_recaller)

        if stdio:
            # stdout is the JSON-RPC channel in stdio mode — keep the status
            # line on stderr so it can't corrupt the protocol stream.
            typer.echo("grag-mcp MCP server ready on stdio", err=True)
            server.run(transport="stdio")
            return

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
        mcp_app = server.streamable_http_app(
            host=settings.mcp_host, transport_security=transport_security
        )
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
