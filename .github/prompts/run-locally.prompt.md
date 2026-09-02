---
mode: agent
description: Run the MCP server locally and ingest content into the graph.
---
Run graph-rag locally and load some content.

Assumes the dev environment is configured (see
`configure-dev-environment.prompt.md`) and Neo4j is up (`make up`,
`make status` → `Neo4j is reachable.`).

1. Ingest content:
   - `make ingest INGEST_PATH=examples/checkov-policies` for the bundled sample,
     or `uv run grag-mcp ingest <path>` for a file or directory the user names.
   - Re-running is cheap: unchanged files (by content hash) are skipped.
   - `--dry-run` previews without writing; `--watch` re-ingests on change.
2. (Optional) `uv run grag-mcp compute-centrality` — GDS PageRank over the
   `CodeEntity` CALLS/IMPORTS graph; needed for `get_central_code_entities`.
   Requires Python source to have been ingested first.
3. Serve:
   - HTTP (default): `make mcp-serve` → `http://127.0.0.1:8765/mcp`.
   - stdio (for clients that spawn the server): `uv run grag-mcp serve-mcp --stdio`.
4. Smoke-test the HTTP server:
   ```bash
   curl -s -X POST http://127.0.0.1:8765/mcp \
     -H 'Content-Type: application/json' \
     -H 'Accept: application/json, text/event-stream' \
     -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"c","version":"0"}}}'
   ```
   Expect HTTP 200 with `"serverInfo":{"name":"graph-rag"}`.

Do not change `MCP_HOST` to `0.0.0.0` on the host, and do not disable the
origin / DNS-rebinding checks. Set `MCP_AUTH_TOKEN` in `.env` if the user wants
a bearer-token gate.
