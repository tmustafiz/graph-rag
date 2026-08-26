from pathlib import Path

from mcp.server import MCPServer

from ..ingestion_pipeline import IngestionPipeline
from ..ingestion_result import IngestionResult
from .models import PolicyResult, SearchResult, SectionDetail, SourceInfo
from .retriever import Retriever

INSTRUCTIONS = (
    "Look up ingested documentation (currently the AWS DMS User Guide). Use "
    "`search` for a natural-language question, `get_section` for the full "
    "text of a known section, `list_sources` to see what's ingested, "
    "`find_policies_for` to see which Checkov policies apply to a Terraform "
    "resource type (e.g. `aws_db_instance`), and `ingest_path` to (re-)ingest "
    "a file or directory after it changes."
)


def build_server(retriever: Retriever, ingestion_pipeline: IngestionPipeline) -> MCPServer:
    """Wires the lookup tools plus `ingest_path` onto a fresh `MCPServer` instance."""
    server = MCPServer(name="graph-rag", instructions=INSTRUCTIONS)

    @server.tool()
    def search(
        query: str,
        top_k: int = 5,
        source_type: str | None = None,
        source_path: str | None = None,
    ) -> list[SearchResult]:
        """Hybrid (vector + full-text) search over ingested document chunks."""
        return retriever.search(query, top_k, source_type, source_path)

    @server.tool()
    def get_section(section_id: str) -> SectionDetail | None:
        """Full text of one section, plus its parent/child outline."""
        return retriever.get_section(section_id)

    @server.tool()
    def list_sources() -> list[SourceInfo]:
        """List every source currently ingested into the graph."""
        return retriever.list_sources()

    @server.tool()
    def find_policies_for(resource_type: str) -> list[PolicyResult]:
        """Checkov policies that apply to a Terraform resource type (e.g. `aws_db_instance`)."""
        return retriever.find_policies_for(resource_type)

    @server.tool()
    def ingest_path(path: str, dry_run: bool = False) -> list[IngestionResult]:
        """(Re-)ingest a file or directory; skips files unchanged since the last ingest."""
        return ingestion_pipeline.run(Path(path), dry_run=dry_run)

    return server
