#!/usr/bin/env python3
"""Claude Code SessionStart hook: recall relevant graph-rag memories into context.

Reads the SessionStart hook payload on stdin (see
https://code.claude.com/docs/en/hooks.md), calls the `recall` tool on a
graph-rag memory MCP server, and prints the results as plain text — Claude
Code injects a SessionStart hook's stdout as additional context.

Configuration (all optional, via environment variables):
  GRAG_MEMORY_MCP_URL      MCP endpoint to recall from.
                            Default: http://127.0.0.1:8766/mcp
                            (docker-compose.memory.yml's default port; use
                            :8765 if pointing at the combined --role all
                            server instead).
  MCP_AUTH_TOKEN            Bearer token, if the server requires one.
  GRAG_MEMORY_RECALL_QUERY  Recall query. Default: the current directory's
                            basename (a reasonable per-project proxy).
  GRAG_MEMORY_RECALL_TOP_K  Max memories to recall. Default: 5.

Requires the `mcp` package (`pip install mcp` or `uv add mcp`; verified
against mcp>=2.1, tested with 2.1.1) on whatever Python interprets this
script. Only `mcp`'s own public API is used — `create_mcp_http_client` builds
the HTTP client the SDK's streamable_http_client expects internally, so this
script never needs to import that HTTP library directly.
"""

import asyncio
import json
import os
import sys

from mcp.client import Client
from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client


async def _recall(url: str, token: str | None, query: str, top_k: int) -> list[dict]:
    headers = {"Authorization": f"Bearer {token}"} if token else None
    async with create_mcp_http_client(headers=headers) as http_client:
        transport = streamable_http_client(url, http_client=http_client)
        async with Client(transport) as client:
            result = await client.call_tool("recall", {"query": query, "top_k": top_k})
            if result.is_error:
                raise RuntimeError(result.content)
            return result.structured_content["result"]


def main() -> int:
    # The hook payload (session_id, cwd, transcript_path, ...) isn't needed
    # here beyond `cwd`, but read it so a bad/missing stdin doesn't crash us.
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        payload = {}
    cwd = payload.get("cwd") or os.getcwd()

    url = os.environ.get("GRAG_MEMORY_MCP_URL", "http://127.0.0.1:8766/mcp")
    token = os.environ.get("MCP_AUTH_TOKEN") or None
    query = os.environ.get("GRAG_MEMORY_RECALL_QUERY") or os.path.basename(cwd.rstrip("/"))
    top_k = int(os.environ.get("GRAG_MEMORY_RECALL_TOP_K", "5"))

    try:
        memories = asyncio.run(_recall(url, token, query, top_k))
    except Exception as exc:  # noqa: BLE001 - a hook must never crash the session
        print(f"[agent-memory] recall skipped: {exc}", file=sys.stderr)
        return 0

    if not memories:
        return 0

    print(f"Relevant memories recalled for '{query}' from graph-rag ({url}):")
    for memory in memories:
        print(f"- ({memory['kind']}) {memory['content']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
