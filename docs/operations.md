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
`grag-mcp ingest` against your source files (a backup is a
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
uv run grag-mcp apply-schema
uv run grag-mcp ingest <your-docs>       # whatever you ingested before
uv run grag-mcp ingest src/graph_rag     # if you were dogfooding on the code
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

`grag-mcp eval-retrieval` runs a small hand-written set of questions
with known-correct sources/sections (`src/graph_rag/eval/retrieval_eval_set.yaml`)
against `search()` and reports pass/fail per case — run it after
changing chunking, embedding, or ranking logic to catch regressions
before they reach an agent:

```bash
uv run grag-mcp eval-retrieval   # or: make eval
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
NEO4J_IMAGE=dhi.io/neo4j:5-dev
BUILDER_IMAGE=dhi.io/python:3.13-dev
RUNTIME_IMAGE=dhi.io/python:3.13
UV_IMAGE=<your-registry>/uv:0.12.5
```

`docker login <registry>` first if the registry needs auth. For Docker
Hardened Images that means `docker login dhi.io` with a DHI subscription;
community access pulls `dhi.io/<image>:<tag>`, while Select/Enterprise
subscribers mirror the repos into their own Docker Hub org and pull
`<your-org>/<image>:<tag>` instead. DHI's Neo4j repository tracks the
Neo4j **5.x** line on a `debian-13` base (`5-dev`, `5.26-dev`, ...), not
the CalVer tags (`2026.07.1`) the Docker Official `neo4j` image uses — so
pin `dhi.io/neo4j:5-dev`, not a `2026.*` tag. APOC and GDS jar versions
must then match that 5.x server line.

The `*_IMAGE` build args are passed by `docker compose build`; to build
the image directly:

```bash
docker build \
  --build-arg BUILDER_IMAGE=dhi.io/python:3.13-dev \
  --build-arg RUNTIME_IMAGE=dhi.io/python:3.13 \
  --build-arg UV_IMAGE=<your-registry>/uv:0.12.5 \
  -t grag-mcp .
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
- **Neo4j** — the substitute must honour `NEO4J_AUTH`. Pick the tag
  variant deliberately:

  - **`dhi.io/neo4j:5-dev`** keeps a shell and package manager, so the
    stock entrypoint's `NEO4J_PLUGINS` boot script (it downloads the
    APOC + GDS jars) and a shell healthcheck still work. It ships
    `neo4j-admin` and `cypher-shell` but **not** `wget`, so the
    `docker-compose.yml` healthcheck still has to change (below). This is
    the pragmatic choice for a database container and still scans at
    0 CVEs.
  - **`dhi.io/neo4j:5`** (runtime, non-dev) has no shell or package
    manager and runs non-root. `NEO4J_PLUGINS` auto-download won't run
    and `CMD-SHELL` healthchecks won't work — you must bake the plugins
    in (below) and use an exec-form healthcheck.

  Swap the healthcheck in `docker-compose.yml` for one the image has:

  ```yaml
  healthcheck:
    test: ["CMD", "cypher-shell", "-u", "neo4j", "-p", "${NEO4J_PASSWORD}",
           "--non-interactive", "RETURN 1"]
    interval: 10s
    timeout: 5s
    retries: 10
  ```

  If the plugin auto-download is unavailable (runtime tag, or an
  air-gapped host that can't reach `github.com`), bake the jars into a
  thin derived image instead:

  ```dockerfile
  FROM dhi.io/neo4j:5-dev
  COPY apoc-*-core.jar gds-*.jar /var/lib/neo4j/plugins/
  ```

  build it, point `NEO4J_IMAGE` at it, and drop `NEO4J_PLUGINS` from the
  compose environment (keep `NEO4J_dbms_security_procedures_unrestricted`).
  GDS is only needed for `compute-centrality`; APOC is used more broadly.

## Ingestion errors and logging

`grag-mcp ingest`/the `ingest_path` MCP tool log a start/end summary
(files processed, skipped, failed) at INFO level, and log a full
traceback for any file that fails to parse/embed/write at ERROR level
— that file is recorded in the results with `error` set rather than
aborting the rest of the batch. Set up log aggregation on the
`mcp-server` container's stdout (`docker compose logs -f mcp-server`)
if running ingestion unattended (e.g. via `ingest_path` from CI).
