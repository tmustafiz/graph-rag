import typer

from graph_rag.graph.client import check_connectivity

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


def main() -> None:
    app()


if __name__ == "__main__":
    main()
