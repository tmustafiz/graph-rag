from pathlib import Path

import typer

from graph_rag.graph.client import check_connectivity, driver_session
from graph_rag.graph.graph_writer import GraphWriter
from graph_rag.graph.schema import apply_schema
from graph_rag.ingest.enricher import Enricher
from graph_rag.ingest.pdf_parser import PdfParser
from graph_rag.ingest.sentence_transformer_embedder import SentenceTransformerEmbedder

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
    if path.suffix.lower() != ".pdf":
        typer.secho(
            f"Unsupported file type: {path.suffix} (only .pdf for now)", fg=typer.colors.RED
        )
        raise typer.Exit(code=1)

    typer.echo(f"Parsing {path}...")
    document = PdfParser().parse(path)
    typer.echo(f"Parsed {len(document.sections)} sections, {len(document.chunks)} chunks.")

    typer.echo("Generating embeddings...")
    document = Enricher(SentenceTransformerEmbedder()).enrich(document)

    typer.echo("Writing to Neo4j...")
    with driver_session() as driver:
        GraphWriter(driver).write(document)

    typer.secho(
        f"Ingested {path}: {len(document.sections)} sections, {len(document.chunks)} chunks.",
        fg=typer.colors.GREEN,
    )


def main() -> None:
    app()


if __name__ == "__main__":
    main()
