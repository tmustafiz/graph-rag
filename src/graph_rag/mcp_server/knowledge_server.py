from pathlib import Path

from mcp.server import MCPServer

from ..ingestion_pipeline import IngestionPipeline
from ..ingestion_result import IngestionResult
from .models import (
    CodeCentralityResult,
    CodeSearchResult,
    NeighborResult,
    OutlineNode,
    PolicyResult,
    SearchResult,
    SectionDetail,
    SourceInfo,
)
from .retriever import Retriever

KNOWLEDGE_INSTRUCTIONS = (
    "Look up whatever has been ingested into this knowledge base — prose/"
    "Markdown documentation, Python source, and Checkov policies. Call "
    "`list_sources` first to see what's actually available. `search` covers ingested "
    "prose/Markdown/generic-YAML chunks ONLY — it does not cover Python code "
    "or Checkov policy text; use `search_code` for a natural-language "
    "question about this codebase's functions/classes, and `search_policies` "
    "for a natural-language question about Checkov policies when you don't "
    "know the exact Terraform resource type. `get_section` returns the full "
    "text of a known section, `get_outline` browses a source's table of "
    "contents, `list_sources` shows what's ingested, `find_policies_for` is "
    "an exact-match traversal from a Terraform resource type (e.g. "
    "`aws_db_instance`) to the policies that apply to it — no fuzzy fallback, "
    "so an empty result may mean the resource type string is off, not that "
    "no policy exists; try `search_policies` instead of guessing variants. "
    "`get_neighbors` walks the graph from any node (Source path, "
    "Section/Chunk/PolicyRule id, CodeEntity qualified_name, or Concept "
    "name). `get_central_code_entities` ranks code by PageRank over the "
    "CALLS/IMPORTS graph — use it to find what's most depended-upon (and "
    "riskiest to change) in this codebase; empty until `grag-mcp "
    "compute-centrality` has been run at least once. `cite` returns a "
    "human-readable citation string for a chunk. `ingest_path` (re-)ingests "
    "a file or directory after it changes. The source list is also browsable "
    "as a resource (`graph-rag://sources`) without a tool call."
)


def register_knowledge_tools(
    server: MCPServer, retriever: Retriever, ingestion_pipeline: IngestionPipeline
) -> None:
    """Wires the search/lookup/ingest tools onto `server`.

    Shared by `build_knowledge_server` (knowledge-only deployments) and
    `build_server` (the combined, default deployment) so the tool bodies
    exist in exactly one place.
    """

    @server.tool()
    def search(
        query: str,
        top_k: int = 5,
        source_type: str | None = None,
        source_path: str | None = None,
    ) -> list[SearchResult]:
        """Hybrid (vector + full-text) search over ingested prose/Markdown/
        generic-YAML document chunks ONLY — does not cover Python code
        (use `search_code`) or Checkov policy text (use `search_policies`).
        """
        return retriever.search(query, top_k, source_type, source_path)

    @server.tool()
    def search_code(query: str, top_k: int = 5) -> list[CodeSearchResult]:
        """Hybrid (vector + full-text) search over this codebase's Python
        functions/classes/modules — the code-search complement to `search`.
        """
        return retriever.search_code(query, top_k)

    @server.tool()
    def get_section(section_id: str, max_chars: int = 8000) -> SectionDetail | None:
        """Full text of one section (truncated past `max_chars`), plus its parent/child outline."""
        return retriever.get_section(section_id, max_chars)

    @server.tool()
    def get_outline(source_path: str) -> list[OutlineNode]:
        """Section outline (table of contents) for a prose source, as a nested tree."""
        return retriever.get_outline(source_path)

    @server.tool()
    def list_sources() -> list[SourceInfo]:
        """List every source currently ingested into the graph."""
        return retriever.list_sources()

    @server.tool()
    def find_policies_for(resource_type: str) -> list[PolicyResult]:
        """Exact-match: Checkov policies whose APPLIES_TO edge names this
        Terraform resource type precisely (e.g. `aws_db_instance`). No fuzzy
        fallback — an empty result may mean the exact spelling is off, not
        that no policy exists; try `search_policies` instead of guessing
        variants.
        """
        return retriever.find_policies_for(resource_type)

    @server.tool()
    def search_policies(query: str, top_k: int = 5) -> list[PolicyResult]:
        """Hybrid (vector + full-text) search over Checkov policy content —
        the semantic/fuzzy complement to `find_policies_for`, for when the
        exact Terraform resource type isn't known.
        """
        return retriever.search_policies(query, top_k)

    @server.tool()
    def get_neighbors(node_id: str, rel_types: list[str] | None = None) -> list[NeighborResult]:
        """Every node directly connected to `node_id`, in both relationship directions.

        `node_id` is matched against whichever unique key its node type uses:
        `Source.path`, `Section`/`Chunk`/`PolicyRule.id`, `CodeEntity.qualified_name`,
        or `Concept.name`. Optionally filter to specific relationship types
        (e.g. `["CALLS", "IMPORTS"]`).
        """
        return retriever.get_neighbors(node_id, rel_types)

    @server.tool()
    def get_central_code_entities(top_k: int = 10) -> list[CodeCentralityResult]:
        """Most central `CodeEntity` nodes by PageRank over the CALLS/IMPORTS
        graph — what's most heavily depended-upon (and riskiest to change).
        Empty until `grag-mcp compute-centrality` has been run at least once.
        """
        return retriever.get_central_code_entities(top_k)

    @server.tool()
    def cite(chunk_id: str) -> str | None:
        """Human-readable citation string for a chunk (source + breadcrumb + page range)."""
        return retriever.cite(chunk_id)

    @server.tool()
    def ingest_path(path: str, dry_run: bool = False) -> list[IngestionResult]:
        """(Re-)ingest a file or directory; skips files unchanged since the last ingest."""
        return ingestion_pipeline.run(Path(path), dry_run=dry_run)

    @server.resource("graph-rag://sources")
    def sources_resource() -> list[SourceInfo]:
        """Browsable list of every ingested source, without a tool call."""
        return retriever.list_sources()


def build_knowledge_server(
    retriever: Retriever, ingestion_pipeline: IngestionPipeline
) -> MCPServer:
    """A standalone MCP server exposing only the knowledge-base tools —
    for a deployment split from agent memory (`serve-mcp --role knowledge`).
    """
    server = MCPServer(name="graph-rag-knowledge", instructions=KNOWLEDGE_INSTRUCTIONS)
    register_knowledge_tools(server, retriever, ingestion_pipeline)
    return server
