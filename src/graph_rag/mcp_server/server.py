from mcp.server import MCPServer

from ..ingestion_pipeline import IngestionPipeline
from ..memory import MemoryRecaller, MemoryWriter
from .knowledge_server import register_knowledge_tools
from .memory_server import register_memory_tools
from .retriever import Retriever

INSTRUCTIONS = (
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
    "Section/Chunk/PolicyRule/AgentMemory id, CodeEntity qualified_name, or "
    "Concept name). `get_central_code_entities` ranks code by PageRank over "
    "the CALLS/IMPORTS graph — use it to find what's most depended-upon (and "
    "riskiest to change) in this codebase; empty until `grag-mcp "
    "compute-centrality` has been run at least once. `cite` returns a "
    "human-readable citation string for a chunk. `ingest_path` (re-)ingests "
    "a file or directory after it changes. Use `remember`/`recall`/`forget` "
    "to save and retrieve your own working memory (decisions, corrections, "
    "findings) across sessions. The source list is also browsable as a "
    "resource (`graph-rag://sources`) without a tool call."
)


def build_server(
    retriever: Retriever,
    ingestion_pipeline: IngestionPipeline,
    memory_writer: MemoryWriter,
    memory_recaller: MemoryRecaller,
) -> MCPServer:
    """Wires every knowledge-base and agent-memory tool onto one `MCPServer`.

    This is `serve-mcp`'s default (`--role all`) — one process, one Neo4j,
    every tool. `build_knowledge_server`/`build_memory_server` split these
    onto independent servers for a split deployment; the tool bodies
    themselves live in `knowledge_server`/`memory_server` so there is exactly
    one copy of each regardless of which server(s) it ends up on.
    """
    server = MCPServer(name="graph-rag", instructions=INSTRUCTIONS)
    register_knowledge_tools(server, retriever, ingestion_pipeline)
    register_memory_tools(server, memory_writer, memory_recaller)
    return server
