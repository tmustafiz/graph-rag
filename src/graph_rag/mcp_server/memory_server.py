from mcp.server import MCPServer

from ..memory import AgentMemory, AgentMemoryResult, MemoryRecaller, MemoryWriter

MEMORY_INSTRUCTIONS = (
    "Save and retrieve your own working memory (decisions, corrections, "
    "findings, preferences, facts) across sessions. `remember` saves one; "
    "`recall` does a hybrid (vector + full-text) search over what's been "
    "saved, ranked by semantic relevance plus a boost for `importance=True` "
    "memories and ones recalled often and recently. `forget` deletes one "
    "immediately rather than waiting for decay-based pruning (`grag-mcp "
    "prune-memory`). Both take an optional `about_qualified_name` to tag or "
    "filter by a CodeEntity's qualified name — this server doesn't need to "
    "know about that entity itself for the tag/filter to work."
)


def register_memory_tools(
    server: MCPServer, memory_writer: MemoryWriter, memory_recaller: MemoryRecaller
) -> None:
    """Wires `remember`/`recall`/`forget` onto `server`.

    Shared by `build_memory_server` (memory-only deployments) and
    `build_server` (the combined, default deployment) so the tool bodies
    exist in exactly one place.
    """

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
        `about_qualified_name`, if given, tags the memory with that `CodeEntity`.
        Set `importance=True` to exempt this memory from decay-based pruning.
        """
        return memory_writer.remember(
            content, kind, about_qualified_name, importance, source_session_id
        )

    @server.tool()
    def recall(
        query: str,
        top_k: int = 5,
        kind: str | None = None,
        about_qualified_name: str | None = None,
        session_id: str | None = None,
    ) -> list[AgentMemoryResult]:
        """Hybrid (vector + full-text) search over your own remembered memories,
        ranked by semantic relevance plus a boost for `importance=True` memories
        and for ones you recall often and recently.

        Optional filters: `kind`
        ("decision"|"correction"|"finding"|"preference"|"fact"),
        `about_qualified_name` (only memories tagged with that `CodeEntity`),
        and `session_id` (only memories saved in that session).
        """
        return memory_recaller.recall(query, top_k, kind, about_qualified_name, session_id)

    @server.tool()
    def forget(memory_id: str) -> None:
        """Explicitly delete a memory now, rather than waiting for decay-based pruning."""
        memory_writer.forget(memory_id)


def build_memory_server(memory_writer: MemoryWriter, memory_recaller: MemoryRecaller) -> MCPServer:
    """A standalone MCP server exposing only `remember`/`recall`/`forget` —
    for a deployment split from the knowledge base (`serve-mcp --role memory`).
    """
    server = MCPServer(name="graph-rag-memory", instructions=MEMORY_INSTRUCTIONS)
    register_memory_tools(server, memory_writer, memory_recaller)
    return server
