# Operations

Backup/restore and other operational notes for the Neo4j-backed graph
(the knowledge base, ingested Sources/Sections/Chunks/CodeEntities/
PolicyRules, and the agent's own `AgentMemory` nodes all live in the
same `neo4j_data` Docker volume).

## `docker compose down -v` — read this first

`docker compose down -v` removes the named volumes (`neo4j_data`,
`neo4j_plugins`), **permanently deleting every ingested Source, Chunk,
CodeEntity, PolicyRule, and AgentMemory** — there is no undo without a
prior backup (see below). Plain `docker compose down` (no `-v`) stops
the containers but keeps the volumes; re-running `docker compose up -d`
picks up right where you left off. Only pass `-v` when you actually
want to wipe the graph and start over.

## Backing up the graph

Neo4j Community edition (what this project runs) doesn't support the
online/hot backup feature — the database has to be stopped for a
consistent dump. A plain volume-level tar archive is simplest here
since the document graph is fully reproducible by re-running
`graph-rag ingest` against your source files (a backup is a
convenience to skip re-ingesting, not the only copy of anything
irreplaceable — except `AgentMemory`, which has no source file).

```bash
# 1. Stop Neo4j (keep the volume, just stop the container using it)
docker compose stop neo4j

# 2. Archive the data volume to a local backups/ directory
mkdir -p backups
docker run --rm \
  -v graph-rag_neo4j_data:/data \
  -v "$(pwd)/backups:/backup" \
  alpine tar czf "/backup/neo4j-data-$(date +%Y%m%d-%H%M%S).tar.gz" -C /data .

# 3. Restart
docker compose start neo4j
```

## Restoring from a backup

```bash
# 1. Stop Neo4j and clear the existing volume's contents
docker compose stop neo4j
docker run --rm -v graph-rag_neo4j_data:/data alpine sh -c "rm -rf /data/*"

# 2. Extract the archive back into the volume
docker run --rm \
  -v graph-rag_neo4j_data:/data \
  -v "$(pwd)/backups:/backup" \
  alpine tar xzf "/backup/neo4j-data-<timestamp>.tar.gz" -C /data

# 3. Restart
docker compose start neo4j
```

The volume name is `<project-directory-name>_neo4j_data` by Docker
Compose's default naming (here, `graph-rag_neo4j_data`) — confirm with
`docker volume ls` if you've renamed the project directory.

## Rebuilding from scratch instead of restoring

Since ingestion is idempotent and content-hash-driven, an
alternative to restoring a backup is simply re-running ingestion after
`docker compose down -v && docker compose up -d`:

```bash
uv run graph-rag apply-schema
uv run graph-rag ingest <your-docs>       # whatever you ingested before
uv run graph-rag ingest src/graph_rag     # if you were dogfooding on the code
```

This reconstructs the document graph, but **not** `AgentMemory` nodes
— agent memory has no source-of-truth file to re-ingest from, so a
volume backup is the only way to preserve it.

## Triggering ingestion over HTTP

`POST /ingest` runs alongside the MCP server (FastAPI, mounted on the
same `serve-mcp` process) — the same operation as the `ingest_path`
MCP tool, for CI or a pre-commit hook that doesn't have an MCP client:

```bash
curl -X POST http://127.0.0.1:8765/ingest \
  -H "Content-Type: application/json" \
  -d '{"path": "src/graph_rag", "dry_run": false}'
```

Returns `200` with a JSON array of per-file results (same shape as
`ingest_path`'s), `422` for a missing/malformed request body, `400`
for a real `path` that no parser can handle. Bound to the same
loopback address and `MCP_AUTH_TOKEN` gate as the MCP server itself.

## Retrieval regression eval

`graph-rag eval-retrieval` runs a small hand-written set of questions
with known-correct sources/sections (`src/graph_rag/eval/retrieval_eval_set.yaml`)
against `search()` and reports pass/fail per case — run it after
changing chunking, embedding, or ranking logic to catch regressions
before they reach an agent:

```bash
uv run graph-rag eval-retrieval   # or: make eval
```

It first ingests the fixture corpus in `src/graph_rag/eval/corpus/`
(idempotent), so it's self-contained and independent of whatever else
you have ingested. Run it from the repo root. Exits non-zero if any
case fails, so it's usable as a CI gate.

## Restricted / hardened-registry environments

Some organizations only allow pulling from an approved hardened-image
registry (Docker Hardened Images at `dhi.io`, Chainguard at `cgr.dev`,
an internal mirror, ...). Every base image `docker compose` uses is
overridable through `.env` so you never edit tracked files:

| Variable | Default | What it is |
| --- | --- | --- |
| `NEO4J_IMAGE` | `neo4j:2026.07.1` | the Neo4j database container |
| `BUILDER_IMAGE` | `python:3.14-slim-trixie` | build stage of the app image |
| `RUNTIME_IMAGE` | `gcr.io/distroless/cc-debian13:nonroot` | runtime stage of the app image |
| `UV_IMAGE` | `ghcr.io/astral-sh/uv:0.12.5` | source of the `uv` binary copied into the build stage |

```bash
# .env
NEO4J_IMAGE=dhi.io/neo4j:2026.07.1
BUILDER_IMAGE=dhi.io/python:3.14-dev
RUNTIME_IMAGE=dhi.io/python:3.14
UV_IMAGE=<your-registry>/uv:0.12.5
```

`docker login <registry>` first if the registry needs auth (`dhi.io`
does). The `*_IMAGE` build args are passed by `docker compose build`; to
build the image directly:

```bash
docker build \
  --build-arg BUILDER_IMAGE=dhi.io/python:3.14-dev \
  --build-arg RUNTIME_IMAGE=dhi.io/python:3.14 \
  --build-arg UV_IMAGE=<your-registry>/uv:0.12.5 \
  -t graph-rag .
```

If no approved registry carries `uv`, publish a minimal image to your
own registry that puts the `uv` binary at `/uv` (from the release
tarball or a vendored copy) and point `UV_IMAGE` at that.

Constraints on substitutes:

- **`BUILDER_IMAGE`** — needs a shell and glibc. `uv` installs a glibc
  `python-build-standalone` interpreter into it, so a musl/Alpine base
  won't work. A `-dev` hardened tag (shell + package manager) is the
  right choice here.
- **`RUNTIME_IMAGE`** — needs glibc, `libgcc`, `libstdc++`
  (torch's C++ runtime) and `ca-certificates`. The `Dockerfile` copies
  the venv with `--chown=nonroot:nonroot` and expects the base to run as
  a non-root user; the common hardened bases (distroless, Chainguard,
  DHI) all use `nonroot` / uid 65532, but if yours differs, adjust the
  `--chown` and add a `USER` line.
- **Neo4j** — the substitute must honour `NEO4J_AUTH`. Two more things
  the stock image gives you that a hardened one may not: the
  `docker-compose.yml` healthcheck shells out to `wget` (swap it for
  `bin/cypher-shell` or a `CMD` the image actually has if `wget` is
  gone), and `NEO4J_PLUGINS` triggers a boot-time shell script that
  downloads the APOC + GDS jars. If that auto-download is missing, bake
  the plugins into a thin derived image instead:

  ```dockerfile
  FROM dhi.io/neo4j:2026.07.1
  COPY apoc-*-core.jar gds-*.jar /var/lib/neo4j/plugins/
  ```

  and drop `NEO4J_PLUGINS` from the compose environment. GDS is only
  needed for `compute-centrality`.

## Ingestion errors and logging

`graph-rag ingest`/the `ingest_path` MCP tool log a start/end summary
(files processed, skipped, failed) at INFO level, and log a full
traceback for any file that fails to parse/embed/write at ERROR level
— that file is recorded in the results with `error` set rather than
aborting the rest of the batch. Set up log aggregation on the
`mcp-server` container's stdout (`docker compose logs -f mcp-server`)
if running ingestion unattended (e.g. via `ingest_path` from CI).
