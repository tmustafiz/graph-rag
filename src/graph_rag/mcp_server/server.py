from pathlib import Path

from mcp.server import MCPServer

from ..ingestion_pipeline import IngestionPipeline
from ..ingestion_result import IngestionResult
from ..memory import AgentMemory, AgentMemoryResult, MemoryRecaller, MemoryWriter
from .models import PolicyResult, SearchResult, SectionDetail, SourceInfo
from .retriever import Retriever

INSTRUCTIONS = (
    "Look up ingested documentation (currently the AWS DMS User Guide). Use "
    "`search` for a natural-language question, `get_section` for the full "
    "text of a known section, `list_sources` to see what's ingested, "
    "`find_policies_for` to see which Checkov policies apply to a Terraform "
    "resource type (e.g. `aws_db_instance`), and `ingest_path` to (re-)ingest "
    "a file or directory after it changes. Use `remember`/`recall`/`forget` "
    "to save and retrieve your own working memory (decisions, corrections, "
    "findings) across sessions."
)


def build_server(
    retriever: Retriever,
    ingestion_pipeline: IngestionPipeline,
    memory_writer: MemoryWriter,
    memory_recaller: MemoryRecaller,
) -> MCPServer:
    """Wires the lookup tools plus `ingest_path`/`remember`/`recall`/`forget`
    onto a fresh `MCPServer` instance.
    """
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

    @server.tool()
    def remember(
        content: str,
        kind: str,
        about_qualified_name: str | None = None,
        importance: bool = False,
        source_session_id: str | None = None,
    ) -> AgentMemory:
        """Save a decision/correction/finding/preference/fact to memory.

        `kind` is one of "decision"|"correction"|"finding"|"preference"|"fact".
        `about_qualified_name`, if given, links the memory to that `CodeEntity`.
        Set `importance=True` to exempt this memory from decay-based pruning.
        """
        return memory_writer.remember(
            content, kind, about_qualified_name, importance, source_session_id
        )

    @server.tool()
    def recall(query: str, top_k: int = 5) -> list[AgentMemoryResult]:
        """Hybrid (vector + full-text) search over your own remembered memories."""
        return memory_recaller.recall(query, top_k)

    @server.tool()
    def forget(memory_id: str) -> None:
        """Explicitly delete a memory now, rather than waiting for decay-based pruning."""
        memory_writer.forget(memory_id)

    return server
