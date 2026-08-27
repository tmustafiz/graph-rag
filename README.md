# graph-rag

Graph RAG knowledge base for coding agents. Ingests heterogeneous docs
(PDF, Markdown, Python, YAML/Checkov) into a Neo4j knowledge graph and
exposes lookup — plus the agent's own working memory — to coding
agents over MCP (Streamable HTTP).

See [docs/IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md) for the
full phased plan and architecture, and
[docs/operations.md](docs/operations.md) for backup/restore and other
day-2 operational notes.

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
make eval     # retrieval regression eval against search() (needs make ingest first)
```

## Code centrality (PageRank)

`graph-rag compute-centrality` runs GDS PageRank over the `CodeEntity`
`CALLS`/`IMPORTS` graph, writing each entity's score to
`CodeEntity.pagerank` — a heavily called/imported entity ranks higher.
Surfaces what's most central (and riskiest to change) in an ingested
codebase, exposed via the `get_central_code_entities` MCP tool. Needs
Python source already ingested (`make ingest` only loads the sample
PDF — run `uv run graph-rag ingest src/graph_rag` first, or point it
at your own codebase) and the `graph-data-science` Neo4j plugin
(already enabled in `docker-compose.yml`):

```bash
uv run graph-rag compute-centrality
```

Re-run after ingesting code changes — scores aren't updated automatically.

## Offline embedding model

`models/all-MiniLM-L6-v2/` vendors the sentence-transformers weights
this repo embeds with (Apache-2.0 licensed, ~87MB), so ingestion and
`serve-mcp` never need to reach `huggingface.co` — useful on networks
that block it. `SentenceTransformerEmbedder` loads from this folder
automatically when present, falling back to downloading
`sentence-transformers/all-MiniLM-L6-v2` from the Hub otherwise. To
refresh it (e.g. after a model update upstream):

```bash
uv run python -c "
from huggingface_hub import snapshot_download
snapshot_download(
    repo_id='sentence-transformers/all-MiniLM-L6-v2',
    local_dir='models/all-MiniLM-L6-v2',
    allow_patterns=['config.json', 'config_sentence_transformers.json',
        'modules.json', 'sentence_bert_config.json', 'special_tokens_map.json',
        'tokenizer.json', 'tokenizer_config.json', 'vocab.txt',
        'model.safetensors', '1_Pooling/*'],
)
"
```

## Ingesting more than the sample PDF

`graph-rag ingest <path>` accepts a single file or a directory
(recursed automatically), parses whichever of PDF/Markdown/Python/YAML
it finds, and upserts into the graph. Re-running it is cheap: any file
whose content hash hasn't changed since the last ingest is skipped
entirely (no re-parse, no re-embedding), and re-ingesting a changed
file removes any Section/Chunk/CodeEntity/PolicyRule it no longer
produces (e.g. a deleted function).

```bash
uv run graph-rag ingest src/graph_rag        # ingest this repo's own source
uv run graph-rag ingest training-docs        # ingest every sample doc/policy
uv run graph-rag ingest some/file.py --dry-run   # preview without writing
uv run graph-rag ingest src/graph_rag --watch    # keep re-ingesting on every change (Ctrl+C to stop)
```

A file that fails to parse/embed/write is reported with its error and
skipped, rather than aborting the rest of a directory ingest — see
[docs/operations.md](docs/operations.md#ingestion-errors-and-logging).

Ingestion is also reachable over plain HTTP once `serve-mcp`/`docker
compose up` is running — `POST /ingest` alongside the MCP server, for
triggering it from CI or a pre-commit hook without an MCP client:

```bash
curl -X POST http://127.0.0.1:8765/ingest \
  -H "Content-Type: application/json" \
  -d '{"path": "src/graph_rag", "dry_run": false}'
```

## MCP server

Exposes lookup and agent-memory tools over Streamable HTTP:

- `search` — hybrid (vector + full-text) search over ingested prose/
  Markdown/generic-YAML chunks. Does **not** cover Python code or
  Checkov policy text — use `search_code`/`search_policies` for those.
- `search_code` — the same hybrid search, over this codebase's Python
  functions/classes/modules.
- `get_section` / `get_outline` — full section text (paginated via
  `max_chars`) or a source's table-of-contents tree.
- `list_sources` — everything currently ingested (also browsable as
  the `graph-rag://sources` MCP **resource**, without a tool call).
- `find_policies_for` — **exact-match** traversal: Checkov policies
  whose `APPLIES_TO` edge names a Terraform resource type precisely
  (e.g. `aws_db_instance`). No fuzzy fallback.
- `search_policies` — the semantic/fuzzy complement: hybrid search
  over Checkov policy content, for when the exact resource type isn't
  known.
- `get_neighbors` — walk the graph from any node (Source path,
  Section/Chunk/PolicyRule/AgentMemory id, CodeEntity qualified_name,
  or Concept name), optionally filtered by relationship type.
- `get_central_code_entities` — most-depended-upon code by PageRank
  over the CALLS/IMPORTS graph. Empty until `graph-rag
  compute-centrality` has been run (see below).
- `cite` — human-readable citation string for a chunk.
- `ingest_path` — (re-)ingest a file or directory from within a
  session.
- `remember` / `recall` / `forget` — the agent's own working memory
  (decisions, corrections, findings), with recency+frequency decay
  pruning (`graph-rag prune-memory --threshold <score>`) — see Phase
  11 in the implementation plan for the full design.

Runs locally:

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
