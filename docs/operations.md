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

`grag-mcp eval-retrieval` runs a small hand-written set of cases
(`src/graph_rag/eval/retrieval_eval_set.yaml`) against `search`,
`search_code`, and `search_policies` — each case names a `tool`, a query,
and the hit it expects (by source + breadcrumb, qualified name, or policy
id), or sets `expect_match: false` for a query that should turn up
nothing. It reports pass/fail per case — run it after changing chunking,
embedding, or ranking logic to catch regressions before they reach an
agent:

```bash
uv run grag-mcp eval-retrieval   # or: make eval
```

It first ingests the fixture corpus in `src/graph_rag/eval/corpus/`
(prose Markdown, a `scheduler.py` module for `search_code`, and
`policies.yaml` for `search_policies`; idempotent), so it's self-contained
and independent of whatever else you have ingested. Run it from the repo
root. Exits non-zero if any case fails, so it's usable as a CI gate.

`--rerank` additionally runs the whole set through the cross-encoder reranker
and prints a baseline-vs-reranked rank comparison — useful when tuning the
reranker or its candidate window.

## Reranking (optional)

`GRAG_RERANK=1` turns on a cross-encoder second stage for `search`,
`search_code`, and `search_policies`: after hybrid search fuses and shortlists,
`cross-encoder/ms-marco-MiniLM-L-6-v2` re-scores those candidates by reading the
query and each document together and reorders by that score (the fused score
breaks ties). It's off by default and adds ~1 model load at startup plus a few
tens of milliseconds per query on CPU. Note the reranker only sees the vector
shortlist, so it can't rescue a hit that only full-text search would surface.

The model is **not** in the Docker image, and there is no implicit
`huggingface.co` download — if reranking is enabled and no model resolves, the
process exits at **startup** with a message naming the fix. Make it available
one of these ways:

```bash
make fetch-reranker                    # vendors it into models/ms-marco-MiniLM-L-6-v2/
export GRAG_RERANK_MODEL=/opt/models/my-reranker   # a local dir...
export GRAG_RERANK_MODEL=cross-encoder/ms-marco-MiniLM-L-6-v2   # ...or a Hub id — the explicit opt-in to an online pull
```

`GRAG_RERANK_MODEL` set to a Hub id is the *only* path that reaches
`huggingface.co`; there is no fallback that does so on its own.

In a container, set `GRAG_RERANK=1` and either mount the model at
`/opt/models/ms-marco-MiniLM-L-6-v2` or set `GRAG_RERANK_MODEL`. When reranking
is on, each hit keeps its `[0, 1]` `score` (the fused value) and adds a
`rerank_score` — the raw cross-encoder logit (unbounded, can be negative).

## Hosted embedding backends (optional)

Ingestion and retrieval embed with the local `all-MiniLM-L6-v2` model by
default — no API key, no outbound calls. To use a hosted provider, set
`GRAG_EMBEDDING_PROVIDER` to `openai`, `ollama`, `voyage`, `cohere`, or `gemini`
(unset or any other value keeps the local model). Each is a plain REST call over
`httpx`; no provider SDK is installed.

```bash
export GRAG_EMBEDDING_PROVIDER=openai
export OPENAI_API_KEY=sk-...
export GRAG_EMBEDDING_MODEL=text-embedding-3-large   # optional; provider default otherwise
export GRAG_EMBEDDING_API_BASE=http://localhost:8000 # optional; OpenAI-compatible gateway or Ollama host
```

Auth env var per provider: `OPENAI_API_KEY`, `VOYAGE_API_KEY`, `CO_API_KEY`,
`GEMINI_API_KEY`; `ollama` needs none. A missing key fails at **startup**.

**Switching providers changes the vector width.** The Neo4j vector index is
created at `EMBEDDING_DIMENSIONS` (384 for the local model; OpenAI `-3-small` is
1536, Gemini/Ollama 768, Voyage/Cohere 1024). To switch:

1. Set `EMBEDDING_DIMENSIONS` to the new model's width in `.env`.
2. Re-run `grag-mcp apply-schema` (drops and recreates the vector indexes).
3. Re-ingest everything — old vectors are the wrong width and won't match.

`build_embedder()` embeds one probe string at startup and refuses to run if the
returned width doesn't equal `EMBEDDING_DIMENSIONS`, so a mismatch surfaces
immediately instead of as a Neo4j error partway through an ingest.

The `Embedder` interface has no query-vs-document distinction, so Cohere and
Voyage requests always send the `document` input type; retrieval queries are
embedded marginally off-optimally on those two providers.

## Pruning agent memory

`AgentMemory` nodes (`remember` / `recall`) grow without bound unless
something prunes them. `grag-mcp prune-memory` does two things each run:

- **soft-delete** (`archived_at` set, still recoverable) any non-`importance`
  memory whose score has decayed below `--threshold` (default `0.5`). Score is
  `(1 + access_count) * exp(-days_since_last_recall / 30)`, so a memory the
  agent keeps recalling survives and one it saved and forgot decays out — a
  never-recalled memory crosses the threshold ~21 days after creation.
- **hard-delete** (`DETACH DELETE`) any memory archived longer than
  `--grace-days` (default `30`) ago — whether archived by decay or by `forget`.

```bash
make prune                          # uv run grag-mcp prune-memory
grag-mcp prune-memory --dry-run     # list what it would soft/hard-delete, write nothing
grag-mcp prune-memory --list-important   # review the importance=True memories (they never decay)
```

It's safe to run unattended. Schedule it however you already run periodic
jobs — e.g. cron:

```cron
# 03:30 daily, against the compose stack's Neo4j
30 3 * * * cd /path/to/graph-rag && docker compose run --rm --no-deps mcp-server prune-memory
```

or a systemd timer:

```ini
# /etc/systemd/system/grag-prune.service
[Service]
Type=oneshot
WorkingDirectory=/path/to/graph-rag
ExecStart=/usr/bin/docker compose run --rm --no-deps mcp-server prune-memory

# /etc/systemd/system/grag-prune.timer
[Timer]
OnCalendar=daily
Persistent=true
[Install]
WantedBy=timers.target
```

The `mcp-server` image's entrypoint is `grag-mcp`, so `docker compose run
--rm mcp-server prune-memory` works with no extra wiring. `importance=True`
memories never decay; `--list-important` surfaces them so you can `forget`
the ones that stopped mattering.

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
NEO4J_IMAGE=dhi.io/neo4j:2026
NEO4J_PLUGINS=
BUILDER_IMAGE=dhi.io/python:3-dev
RUNTIME_IMAGE=dhi.io/python:3
UV_IMAGE=<your-registry>/uv:0.12.5
```

`docker login <registry>` first if the registry needs auth. For Docker
Hardened Images that means `docker login dhi.io` with a DHI subscription;
community access pulls `dhi.io/<image>:<tag>`, while Select/Enterprise
subscribers mirror the repos into their own Docker Hub org and pull
`<your-org>/<image>:<tag>` instead. DHI's Neo4j image is the **Community**
edition on the same CalVer stream as the Docker Official image
(`dhi.io/neo4j:2026` == `2026.07.1-debian13`, `variant=runtime`), runs as
uid 7474, and scans at 0 CVEs. It ships `bash`, `cypher-shell`,
`neo4j-admin` and a JRE, but **no `wget`/`curl` and no `awk`** — see the
Neo4j constraints below, which `docker-compose.yml` and `.env` already
account for.

The `*_IMAGE` build args are passed by `docker compose build`; to build
the image directly:

```bash
docker build \
  --build-arg BUILDER_IMAGE=dhi.io/python:3-dev \
  --build-arg RUNTIME_IMAGE=dhi.io/python:3 \
  --build-arg UV_IMAGE=<your-registry>/uv:0.12.5 \
  -t grag-mcp .
```

Pin the minor (`dhi.io/python:3.14`) rather than the floating `3` for a
reproducible runtime layer once you know which minor your registry
carries.

If no approved registry carries `uv`, publish a minimal image to your
own registry that puts the `uv` binary at `/uv` (from the release
tarball or a vendored copy) and point `UV_IMAGE` at that.

Constraints on substitutes:

- **`BUILDER_IMAGE`** — a throwaway build stage; it does **not** ship in
  the final image and isn't in the Trivy scan, so its CVEs don't reach
  the artifact — override it only for registry-policy or build-time
  supply-chain reasons. Needs a shell and glibc: `uv` installs a glibc
  `python-build-standalone` interpreter into it, so a musl/Alpine base
  won't work. `dhi.io/python:3-dev` (root, `bash`, `apt`, debian-13)
  drops straight in — the stage's own Python version is irrelevant, `uv`
  installs CPython 3.13 separately.
- **`RUNTIME_IMAGE`** — this one ships. Needs glibc, `libgcc_s`,
  `libstdc++` (torch's C++ runtime), `libssl` / `libffi` / `libz` /
  `libexpat` (the standalone CPython's stdlib modules), and
  `ca-certificates`. It does **not** need Python — the app runs on the
  CPython 3.13 copied from the builder into `/opt/python`. The
  `Dockerfile` copies the venv with `--chown=65532:65532` and sets
  `USER 65532`; both `gcr.io/distroless/cc-debian13:nonroot` (the
  default) and `dhi.io/python:3` use that uid. `dhi.io/python:3` works
  (verified: torch/numpy/sentence-transformers import and run) even
  though it has no system `libgomp` — the PyTorch CPU wheel bundles its
  own OpenMP. Its bundled Python 3.14 goes unused, costing ~70 MB over
  distroless. If your base uses a different uid, change both the
  `--chown` and the `USER` line.
- **Neo4j** — the substitute must be **Community** edition and honour
  `NEO4J_AUTH`. `dhi.io/neo4j:2026` works with the tweaks already baked
  into `docker-compose.yml`, but two missing tools change how you feed it
  config:

  - **No `wget`/`curl`.** The stock entrypoint downloads `NEO4J_PLUGINS`
    (APOC, GDS) on boot with `wget`; the DHI image can't. Set
    `NEO4J_PLUGINS=` in `.env` to stop it trying, and preload the jars
    into the `neo4j_plugins` volume instead (below). The compose file
    mounts that volume at `/var/lib/neo4j/plugins` — Neo4j's default
    plugin dir, on the JVM classpath — so any jar dropped there loads
    with no further config.
  - **No `awk`.** The entrypoint's loop that turns `NEO4J_server_*` /
    `NEO4J_dbms_*` environment variables into `neo4j.conf` lines is
    `set | grep ^NEO4J_ | awk …` and silently produces nothing without
    `awk`. Only `NEO4J_AUTH`, `NEO4J_PLUGINS` (as a trigger),
    `NEO4J_EDITION` and `NEO4J_ACCEPT_LICENSE_AGREEMENT` are handled
    directly. **Any other Neo4j setting you need must come from a file** —
    a full `neo4j.conf` bind-mounted over `/var/lib/neo4j/conf/neo4j.conf`,
    a script pointed at by `EXTENSION_SCRIPT` that appends to it, or a
    derived image. This project needs none: the GDS procedures
    `compute-centrality` calls (`gds.graph.project`, `gds.pageRank.write`,
    `gds.graph.drop`) run without `dbms.security.procedures.unrestricted`,
    and the code calls no APOC procedures, so the
    `NEO4J_dbms_security_procedures_unrestricted` line in the compose file
    is a harmless no-op here.
  - **Healthcheck.** `docker-compose.yml` already uses `cypher-shell`
    (present in both images) rather than `wget`.

  Preload APOC + GDS into the volume once. Simplest: bring the stack up
  on the **stock** image first (`NEO4J_IMAGE` unset) so its entrypoint
  downloads the jars into `graph-rag_neo4j_plugins`, then `docker compose
  down`, set `NEO4J_IMAGE=dhi.io/neo4j:2026` + `NEO4J_PLUGINS=` in `.env`,
  and `docker compose up -d` again — the volume keeps the jars. Air-gapped,
  copy jars you already have straight into the volume:

  ```bash
  docker run --rm -v graph-rag_neo4j_plugins:/plugins -v "$PWD":/host busybox \
    sh -c 'cp /host/apoc-*.jar /plugins/apoc.jar &&
           cp /host/graph-data-science-*.jar /plugins/graph-data-science.jar'
  ```

  For a fully self-contained artifact, bake them into a derived image
  instead:

  ```dockerfile
  FROM dhi.io/neo4j:2026
  COPY apoc-*.jar graph-data-science-*.jar /var/lib/neo4j/plugins/
  ```

## Ingestion errors and logging

`grag-mcp ingest`/the `ingest_path` MCP tool log a start/end summary
(files processed, skipped, failed) at INFO level, and log a full
traceback for any file that fails to parse/embed/write at ERROR level
— that file is recorded in the results with `error` set rather than
aborting the rest of the batch. Set up log aggregation on the
`mcp-server` container's stdout (`docker compose logs -f mcp-server`)
if running ingestion unattended (e.g. via `ingest_path` from CI).
