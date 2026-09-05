#!/usr/bin/env python3
"""VS Code Copilot Chat SessionStart hook: recall graph-rag memories into context.

Copilot Chat's hooks feature (Preview, per VS Code's own docs — the config
format may still change) is close to Claude Code's: a `.github/hooks/*.json`
config runs a command on each hook event and reads JSON back from its
stdout. See `agent-memory.hooks.json` next to this file, and
https://code.visualstudio.com/docs/agent-customization/hooks /
https://code.visualstudio.com/docs/agents/reference/hooks-reference for the
official reference this was written against.

Reads the SessionStart payload on stdin (`cwd`, `session_id`,
`hook_event_name`, `transcript_path`, `timestamp`, `source`; this script only
needs `cwd`), calls `recall` on a graph-rag memory MCP server, and prints
`{"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": "..."}}`
on stdout — the shape Copilot injects as context at the start of a session.
Prints nothing (valid: no context to add) when there's nothing to recall or
the server can't be reached; never fails the session.

Configuration (all optional, via environment variables) — same as the
Claude Code version of this hook (../../claude/hooks/session_start_recall.py):
  GRAG_MEMORY_MCP_URL      MCP endpoint to recall from.
                            Default: http://127.0.0.1:8766/mcp
  MCP_AUTH_TOKEN            Bearer token, if the server requires one.
  GRAG_MEMORY_RECALL_QUERY  Recall query. Default: the cwd's basename.
  GRAG_MEMORY_RECALL_TOP_K  Max memories to recall. Default: 5.

Requires the `mcp` package (`pip install mcp` or `uv add mcp`) on whatever
Python interprets this script — it pulls in `httpx2` as a dependency, which
is what this script uses (the SDK's streamable_http_client is typed against
`httpx2.AsyncClient`, not the classic `httpx` package).
"""

import asyncio
import json
import os
import sys

import httpx2
from mcp.client import Client
from mcp.client.streamable_http import streamable_http_client


async def _recall(url: str, token: str | None, query: str, top_k: int) -> list[dict]:
    headers = {"Authorization": f"Bearer {token}"} if token else None
    async with httpx2.AsyncClient(headers=headers, timeout=10.0) as http_client:
        transport = streamable_http_client(url, http_client=http_client)
        async with Client(transport) as client:
            result = await client.call_tool("recall", {"query": query, "top_k": top_k})
            if result.is_error:
                raise RuntimeError(result.content)
            return result.structured_content["result"]


def main() -> int:
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

    lines = [f"Relevant memories recalled for '{query}' from graph-rag ({url}):"]
    lines += [f"- ({memory['kind']}) {memory['content']}" for memory in memories]
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "SessionStart",
                    "additionalContext": "\n".join(lines),
                }
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
