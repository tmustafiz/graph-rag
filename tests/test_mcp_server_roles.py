from unittest.mock import MagicMock

from graph_rag.mcp_server.knowledge_server import build_knowledge_server
from graph_rag.mcp_server.memory_server import build_memory_server
from graph_rag.mcp_server.server import build_server

KNOWLEDGE_TOOL_NAMES = {
    "search",
    "search_code",
    "get_section",
    "get_outline",
    "list_sources",
    "find_policies_for",
    "search_policies",
    "get_neighbors",
    "get_central_code_entities",
    "cite",
    "ingest_path",
}
MEMORY_TOOL_NAMES = {"remember", "recall", "forget"}


def _tool_names(server) -> set[str]:  # noqa: ANN001
    return {tool.name for tool in server._tool_manager.list_tools()}


def _resource_uris(server) -> set[str]:  # noqa: ANN001
    return {str(resource.uri) for resource in server._resource_manager.list_resources()}


def test_knowledge_server_exposes_only_knowledge_tools() -> None:
    server = build_knowledge_server(MagicMock(), MagicMock())

    assert _tool_names(server) == KNOWLEDGE_TOOL_NAMES
    assert "graph-rag://sources" in _resource_uris(server)
    assert server.name == "graph-rag-knowledge"


def test_memory_server_exposes_only_memory_tools() -> None:
    server = build_memory_server(MagicMock(), MagicMock())

    assert _tool_names(server) == MEMORY_TOOL_NAMES
    assert _resource_uris(server) == set()
    assert server.name == "graph-rag-memory"


def test_combined_server_exposes_every_tool_on_one_server() -> None:
    server = build_server(MagicMock(), MagicMock(), MagicMock(), MagicMock())

    assert _tool_names(server) == KNOWLEDGE_TOOL_NAMES | MEMORY_TOOL_NAMES
    assert "graph-rag://sources" in _resource_uris(server)
    assert server.name == "graph-rag"
