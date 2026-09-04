from enum import StrEnum


class McpRole(StrEnum):
    """Which MCP tools `serve-mcp` exposes.

    `KNOWLEDGE` and `MEMORY` let the knowledge base and agent memory run as
    independent deployments (own process, own Neo4j); `ALL` is the original,
    single-server behavior and stays the default.
    """

    KNOWLEDGE = "knowledge"
    MEMORY = "memory"
    ALL = "all"
