from mcp.server import MCPServer

from .models import PolicyResult, SearchResult, SectionDetail, SourceInfo
from .retriever import Retriever

INSTRUCTIONS = (
    "Look up ingested documentation (currently the AWS DMS User Guide). Use "
    "`search` for a natural-language question, `get_section` for the full "
    "text of a known section, `list_sources` to see what's ingested, and "
    "`find_policies_for` to see which Checkov policies apply to a Terraform "
    "resource type (e.g. `aws_db_instance`)."
)


def build_server(retriever: Retriever) -> MCPServer:
    """Wires the read-only lookup tools onto a fresh `MCPServer` instance."""
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

    return server
