---
mode: agent
description: Build and deploy the full stack (Neo4j + MCP server) with Docker Compose.
---
Deploy the whole stack with Docker Compose.

1. `docker compose build` — multi-stage: the app venv is built against a
   standalone CPython (via `uv`) and copied into a distroless runtime image
   (no shell, non-root uid 65532). Entry point is `/app/.venv/bin/grag-mcp`.
2. `docker compose up -d` — starts `graph-rag-neo4j` then `graph-rag-mcp`
   (the latter waits on the Neo4j healthcheck). Ports are published on
   `127.0.0.1` only: `7474`/`7687` (Neo4j), `8765` (MCP).
3. Verify:
   - `docker compose ps` — both up, `graph-rag-neo4j` healthy.
   - `docker compose exec -T mcp-server grag-mcp status` → `Neo4j is reachable.`
   - `curl` the MCP `initialize` (see `run-locally.prompt.md`) → 200,
     `"serverInfo":{"name":"graph-rag"}`.
   - `docker compose logs mcp-server` → `MCP server listening on …:8765/mcp`.

Hardened / restricted registries: every base image is overridable via `.env`
(`NEO4J_IMAGE`, `BUILDER_IMAGE`, `RUNTIME_IMAGE`, `UV_IMAGE`). For Docker
Hardened Images the working set is `NEO4J_IMAGE=dhi.io/neo4j:2026` +
`NEO4J_PLUGINS=` (that image has no wget/awk, so preload APOC/GDS jars into the
`neo4j_plugins` volume), `BUILDER_IMAGE=dhi.io/python:3-dev`,
`RUNTIME_IMAGE=dhi.io/python:3`. Full recipe and constraints:
[`docs/operations.md`](../../docs/operations.md) → "Restricted / hardened-registry
environments". Keep the tracked defaults public and overridable — don't hardcode
a `dhi.io/...` image as the default.

Opt-in split deployment: `docker-compose.knowledge.yml` and
`docker-compose.memory.yml` run the knowledge base and agent memory as two
fully independent stacks (separate Neo4j, separate MCP server, separate
volumes, optionally separate hosts) instead of the combined stack above —
`docker compose -f docker-compose.knowledge.yml up -d --build` and the same
for `.memory.yml`. Each provisions a brand-new Neo4j, so run
`grag-mcp apply-schema` against each before first use. With the stock
`NEO4J_IMAGE`, each fresh stack's entrypoint auto-downloads its own APOC/GDS
jars on first boot, same as the combined stack. If `NEO4J_IMAGE`/
`NEO4J_PLUGINS` are overridden for a hardened registry (no wget — see
"Restricted / hardened-registry environments" below), each split stack's
`_plugins` volume needs those jars preloaded independently — a fresh split
stack won't inherit jars already preloaded into the combined stack's volume.
See [`docs/operations.md`](../../docs/operations.md) → "Split deployment
(optional)".
