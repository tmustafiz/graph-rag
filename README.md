# graph-rag

Graph RAG knowledge base for coding agents. Ingests heterogeneous docs
(PDF, Markdown, Python, YAML) into a Neo4j knowledge graph and exposes
lookup to coding agents over MCP (Streamable HTTP).

See [docs/IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md) for the
full phased plan and architecture.

## Quickstart

```bash
cp .env.example .env      # adjust NEO4J_PASSWORD if you like
make install               # uv sync
make up                    # start Neo4j via Docker
make status                 # verify connectivity from the CLI
make apply-schema           # create constraints, full-text + vector indexes
make ingest                 # parse, embed, and load training-docs/dms-ug.pdf
```

Neo4j Browser: http://localhost:7474 (auth: `neo4j` / value of `NEO4J_PASSWORD`).

```bash
make down     # stop Neo4j
make lint     # ruff
make test     # pytest
```

## MCP server

Exposes read-only lookup tools (`search`, `get_section`, `list_sources`) over
Streamable HTTP for coding agents. Runs locally:

```bash
make mcp-serve   # http://127.0.0.1:8765/mcp
```

or as its own `docker-compose` service alongside Neo4j:

```bash
docker compose up -d
```

`.mcp.json` at the repo root already registers it for this project. Bound to
`127.0.0.1` only; set `MCP_AUTH_TOKEN` in `.env` for an extra bearer-token
check (defense in depth — see `docs/IMPLEMENTATION_PLAN.md` Phase 3).
